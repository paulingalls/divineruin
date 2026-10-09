import copy
import json
import math
import random

import pytest
from creature_combat_helpers import ATTRIBUTES, ROOT, catalog, participant, row, selected

from check_resolution_attack import resolve_attack
from combat_state import CombatState
from combat_support import _participant_roster
from creature_combat import translate_creature
from encounter_loot import calculate_currency_drop, derive_role_loot


def translate(source, role="standard"):
    return translate_creature(source, encounter_id="enc137", enemy_id="enemy137", role=role)


@pytest.mark.parametrize("source", selected(), ids=lambda r: r["id"])
@pytest.mark.parametrize("role", ["minion", "standard", "elite", "boss"])
def test_selected_species_role_matrix(source, role):
    enemy = translate(source, role)
    hp = {
        "minion": max(1, source["hp"] // 2),
        "standard": source["hp"],
        "elite": math.ceil(source["hp"] * 1.5),
        "boss": source["hp"] * 2,
    }[role]
    assert enemy["xp_value"] == int(source["xp_reward"] * {"minion": 0.5, "standard": 1, "elite": 1.5, "boss": 2}[role])
    assert enemy["hp"] == hp
    assert enemy["ac"] == source["ac"] + {"minion": -1, "standard": 0, "elite": 1, "boss": 2}[role]
    assert enemy["legendary_actions"] == (1 if role == "boss" else 0)
    assert enemy["signature_ability"] == (source.get("signature_ability") if role == "boss" else None)
    assert enemy["action_pool"]
    executable = [*source["attacks"], *[a for a in source["actives"] if "kind" in a]]
    if role == "minion":
        executable = [
            a
            for a in executable
            if a.get("kind", "attack") == "attack"
            and a["damage"] != "0"
            and "recharge" not in a
            and a.get("type") != "area"
            and not a.get("self_heal")
            and not set(a.get("properties", [])) & {"aoe", "buff", "healing", "control", "debuff"}
        ]
    assert {a["name"] for a in enemy["action_pool"]} == {a["name"] for a in executable}
    if role == "minion":
        assert all(
            a.get("kind", "attack") == "attack"
            and a["damage"] != "0"
            and "recharge" not in a
            and not set(a["properties"]) & {"aoe", "buff", "healing", "control", "debuff"}
            for a in enemy["action_pool"]
        )
    if role in ("elite", "boss"):
        for action in enemy["action_pool"]:
            if action.get("kind", "attack") != "attack" or "recharge" in action or action["damage"] == "0":
                assert action["enhanced"] is True


@pytest.mark.parametrize("source", selected(), ids=lambda r: r["id"])
def test_catalog_fields_and_authored_attack_survive(source):
    enemy = translate(source)
    assert enemy["id"] == "enemy137" and enemy["creature_id"] == source["id"]
    for key in ("hp", "ac", "level", "tier", "loot_table_id"):
        assert enemy[key] == source[key]
    assert enemy["xp_value"] == source["xp_reward"]
    assert enemy["attributes"] == {ATTRIBUTES[k]: v for k, v in source["attributes"].items()}
    assert enemy["saving_throw_proficiencies"] == [ATTRIBUTES[k] for k in source["save_proficiencies"]]
    assert enemy["resistance_tags"] == source.get("resistance_tags", [])
    for authored in source["attacks"]:
        action = next(a for a in enemy["action_pool"] if a["name"] == authored["name"])
        assert action["to_hit"] == authored["to_hit"]
        assert action["damage"] == authored["damage"]
        assert action["attack_source"] == "catalog"


@pytest.mark.parametrize("role", ["minion", "standard", "elite", "boss"])
def test_translation_and_derivation_do_not_alias_source(role):
    source = row("hollow_mawling")
    before = copy.deepcopy(source)
    enemy = translate(source, role)
    enemy["attributes"]["strength"] = 999
    enemy["catalog_audio"]["special"]["new"] = "new"
    enemy["catalog_narration"]["attack_cue"] = "changed"
    enemy["action_pool"][0]["properties"].append("changed")
    enemy["deferred_effects"][0]["source"]["special"] = "changed"
    assert source == before


def test_properties_union_and_kinds():
    source = row("bandit")
    source["attacks"][1]["properties"] = ["finesse", "ranged"]
    result = translate(source)
    assert result["action_pool"][1]["properties"] == ["finesse", "ranged"]
    captain = translate(row("bandit_captain"))
    assert next(a for a in captain["action_pool"] if a["name"] == "Rally")["properties"] == ["healing"]
    assert next(a for a in captain["action_pool"] if a["name"] == "Dirty Fighting")["properties"] == ["buff"]
    area = next(a for a in translate(row("cult_leader"))["action_pool"] if a["type"] == "area")
    assert "aoe" in area["properties"]
    assert next(a for a in translate(row("hollow_warden"))["action_pool"] if a["name"] == "Absorb")["properties"] == [
        "healing"
    ]


def test_selected_structured_mechanics():
    bandit = row("bandit")["actives"][0]
    assert {
        k: bandit[k]
        for k in ("kind", "damage", "damage_type", "applies_condition", "save", "dc", "duration", "recharge")
    } == {
        "kind": "attack",
        "damage": "0",
        "damage_type": "none",
        "applies_condition": "blinded",
        "save": "DEX",
        "dc": 12,
        "duration": 1,
        "recharge": {"kind": "encounter", "uses": 1},
    }
    rally, dirty = row("bandit_captain")["actives"]
    assert rally["kind"] == "healing" and rally["healing"] == "1d8" and rally["target_group"] == "allied_bandits"
    assert dirty["kind"] == "prepare_attack" and dirty["advantage"] is True
    assert dirty["on_hit"] == {"applies_condition": "blinded", "duration": 1}
    for action in (rally, dirty):
        assert action["recharge"] == {"kind": "encounter", "uses": 1}
    lunge = row("hollow_mawling")["attacks"][2]
    assert lunge["advantage"] is True and lunge["escape_dc"] == 13
    assert lunge["recharge"] == {"kind": "roll", "die": 6, "threshold": 5}
    assert row("hollow_warden")["attacks"][2]["self_heal"] == "damage_dealt"


class FixedRandom(random.Random):
    def random(self):
        return 0

    def randint(self, low, high):
        return min(3, high)


@pytest.mark.parametrize("source", selected(), ids=lambda r: r["id"])
def test_translated_categories_and_loot_use_catalog(source):
    enemy = translate(source)
    expected_category = "hollow_" + source["hollow"]["class"] if source["category"] == "hollow" else source["category"]
    assert enemy["category"] == expected_category
    expected_coin = {"humanoid": 3, "hollow_drift": 0, "hollow_rend": 6, "hollow_wrack": 6}[expected_category] * source[
        "tier"
    ]
    assert calculate_currency_drop(enemy["category"], enemy["tier"], enemy["role"], FixedRandom()) == expected_coin
    tables = json.loads((ROOT / "content/loot_tables.json").read_text())
    table = next(t for t in tables if t["id"] == enemy["loot_table_id"])
    expected = [
        {
            "item_id": d["item_id"],
            "quantity": {"1d4": 3, "1d6": 3, "2d4": 6, "2d6": 6}[d["quantity"]]
            if isinstance(d["quantity"], str)
            else d["quantity"],
        }
        for d in table["drops"]
        if d["chance"] > 0
    ]
    assert derive_role_loot(table, enemy["role"], FixedRandom()) == expected
    assert calculate_currency_drop("named", 3, "boss", FixedRandom()) == 0


@pytest.mark.parametrize("source", selected(), ids=lambda r: r["id"])
def test_catalog_metadata_roundtrips_and_roster_exposes_effects(source):
    enemy = translate(source)
    p = participant(enemy)
    state = CombatState("combat137", [p], [p.id])
    restored = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    summary = _participant_roster(restored.participants)[0]
    for key in ("creature_id", "catalog_narration", "catalog_audio", "deferred_effects"):
        assert summary[key] == enemy[key]
    assert summary["catalog_narration"] == source["narration"]
    assert summary["catalog_audio"] == source["audio"]
    expected = {a["name"] for a in enemy["action_pool"]}
    if enemy["multiattack_sequence"]:
        expected.add(enemy["multiattack_sequence"]["name"])
    assert {a["name"] for a in summary["executable_actions"]} == expected
    assert all(a["kind"] in ("command", "accusation") for a in summary["mark_actions"])


def test_dm_inventory_has_no_false_executables():
    expected = {
        "ashmark_sergeant": {("actives", "Accusation"), ("actives", "Rally")},
        "ashmark_soldier": {("attacks", "Shield Bash")},
        "bandit": {("actives", "Dirty Fighting")},
        "bandit_captain": {
            ("actives", "Dirty Fighting"),
            ("actives", "Rally"),
            ("multiattack", "2 attacks with Longsword or 2 Crossbow shots"),
            ("passives", "Cunning Action"),
            ("passives", "Leadership Aura"),
        },
        "cult_fanatic": {("actives", "Bless")},
        "cult_leader": {("signature_ability", "Mantle of Ruin"), ("attacks", "Hold Person")},
        "cultist": set(),
        "hollow_knight": {
            ("actives", "Command Lesser"),
            ("actives", "Dissolution Strike"),
            ("actives", "Unholy Fortitude"),
            ("attacks", "Corrupted Blade"),
            ("attacks", "Shield Slam"),
            ("hollow", "hollow"),
            ("multiattack", "2 attacks with Corrupted Blade"),
            ("passives", "Corrupted Resilience"),
            ("passives", "Fragment Voice"),
            ("passives", "Remnant Tactics"),
        },
        "hollow_mawling": {
            ("actives", "Lunge"),
            ("actives", "Scatter"),
            ("attacks", "Claw"),
            ("attacks", "Lunge"),
            ("hollow", "hollow"),
            ("passives", "Adaptive Learning"),
            ("passives", "Dissolution Field"),
            ("passives", "Unsettling Silence"),
        },
        "hollow_shadeling": {
            ("attacks", "Corrosive Touch"),
            ("hollow", "hollow"),
            ("passives", "Amorphous"),
            ("passives", "Corruption Trail"),
            ("passives", "Sunlight Sensitivity"),
        },
        "hollow_warden": {("attacks", "Absorb"), ("hollow", "hollow"), ("signature_ability", "Reality Collapse")},
        "hollow_wisp": {("hollow", "hollow")},
        "hollowed_scout": {("hollow", "hollow")},
    }
    for source in selected():
        enemy = translate(source)
        effects = {(e["group"], e["name"]): e for e in enemy["deferred_effects"]}
        assert set(effects) == expected[source["id"]]
        for (group, name), effect in effects.items():
            authored = source[group]
            if isinstance(authored, list):
                authored = next(entry for entry in authored if entry["name"] == name)
            elif group == "hollow":
                authored = {k: v for k, v in authored.items() if k not in {"corruption_aura", "resonance_on_death"}}
            assert effect["source"] == authored
        if source["id"] == "hollow_mawling":
            assert [a["name"] for a in enemy["action_pool"]].count("Lunge") == 1
        if source["id"] == "bandit_captain":
            summary = _participant_roster([participant(enemy)])[0]
            assert not summary["mark_actions"]
            assert {a["name"] for a in summary["executable_actions"] if a["declaration_type"] == "ability"} == {
                "Rally",
                "Dirty Fighting",
            }


def test_boss_signature_does_not_alias_source():
    source = row("hollow_warden")
    before = copy.deepcopy(source)
    enemy = translate(source, "boss")
    enemy["signature_ability"]["description"] = "changed"
    assert source == before


@pytest.mark.parametrize("species", ["hollow_hollowmoth", "rock_viper"])
@pytest.mark.parametrize("damage", [None, "7"])
def test_catalog_flat_damage_reaches_real_dice_consumer(species, damage):
    source = next(r for r in catalog() if r["id"] == species)
    if damage is not None:
        source["attacks"][0]["damage"] = damage
    before = copy.deepcopy(source)
    enemy = translate(source)
    action = enemy["action_pool"][0]
    result = resolve_attack(enemy, action, target_ac=0, target_hp=10, rng=random.Random(0))
    assert result.hit and not result.critical_success
    assert result.damage == int(source["attacks"][0]["damage"])
    assert source == before


RIDER = {"save": "CON", "dc": 13, "dice": "1d4", "target": "selected_player_held_item"}


def test_maw_durability_contract_survives_translation():
    from creature_schema import validate_creature_stat_block

    source = row("hollow_mawling")
    assert validate_creature_stat_block(source) == []
    attack = next(a for a in translate(source)["action_pool"] if a["name"] == "Dissolution Maw")
    assert attack["durability_rider"] == RIDER


@pytest.mark.parametrize(
    "rider",
    [
        None,
        {},
        {**RIDER, "save": "bad"},
        {**RIDER, "dc": True},
        {**RIDER, "dc": 0},
        {**RIDER, "dice": "bad"},
        {**RIDER, "target": "armor"},
        {**RIDER, "extra": 1},
        {k: v for k, v in RIDER.items() if k != "dice"},
    ],
)
def test_maw_rejects_invalid_durability_contract(rider):
    from creature_schema import validate_creature_stat_block

    source = copy.deepcopy(row("hollow_mawling"))
    source["attacks"][1]["durability_rider"] = rider
    assert validate_creature_stat_block(source)


def test_maw_rejects_rider_on_nonattack():
    from creature_schema import validate_creature_stat_block

    source = copy.deepcopy(row("hollow_mawling"))
    source["actives"][0] = {
        "name": "Preparation",
        "description": "Prepare a strike.",
        "narration_cue": "It braces.",
        "audio": None,
        "kind": "prepare_attack",
        "advantage": True,
        "on_hit": {"applies_condition": "prone", "duration": 1},
    }
    assert validate_creature_stat_block(source) == []
    source["actives"][0]["durability_rider"] = RIDER
    assert validate_creature_stat_block(source)
