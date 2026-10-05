import copy

import pytest
from creature_combat_helpers import catalog, row

from creature_combat import translate_creature
from creature_schema import validate_creature_stat_block


def translate(source, **kwargs):
    return translate_creature(
        source, **{"encounter_id": "enc137", "enemy_id": "enemy137", "role": "standard", **kwargs}
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(id=""),
        lambda r: r.update(hp="ten"),
        lambda r: r.update(attacks=None),
        lambda r: r.update(actives=None),
        lambda r: r["attributes"].update(STR="strong"),
        lambda r: r.update(save_proficiencies=["BAD"]),
        lambda r: r["attacks"][0].update(to_hit="four"),
        lambda r: r["attacks"][0].update(damage="oops"),
        lambda r: r["attacks"][0].update(properties=["grapple"]),
        lambda r: r["attacks"][0].update(applies_condition="unknown", save="DEX", dc=12),
        lambda r: r["attacks"][0].update(recharge={"kind": "roll", "die": 6, "threshold": 7}),
    ],
)
def test_translation_rejects_invalid_identity_and_fields(mutation):
    source = row("bandit")
    mutation(source)
    with pytest.raises(ValueError, match=r"creature .*encounter .*enemy "):
        translate(source)


@pytest.mark.parametrize("kwargs", [{"enemy_id": ""}, {"encounter_id": None}, {"role": "custom"}, {"role": "named"}])
def test_translation_rejects_bad_boundary(kwargs):
    with pytest.raises(ValueError, match=r"creature .*encounter .*enemy "):
        translate(row("bandit"), **kwargs)


def test_translation_rejects_named_custom_and_unusable_pool():
    source = row("hollow_knight")
    source["hollow"]["class"] = "named"
    with pytest.raises(ValueError, match="Named/custom"):
        translate(source)
    source = row("bandit")
    source["category"] = "elemental"
    with pytest.raises(ValueError, match="unsupported category"):
        translate(source)
    for attacks in ([], [{**source["attacks"][0], "recharge": {"kind": "encounter", "uses": 1}}]):
        source = row("bandit")
        source["attacks"] = attacks
        source["actives"] = []
        with pytest.raises(ValueError, match="no usable damaging attack"):
            translate(source, role="minion")
    source = row("bandit")
    source["actives"].append({**source["actives"][0], "name": source["attacks"][0]["name"]})
    with pytest.raises(ValueError, match=r"Short Sword.*duplicate"):
        translate(source)


@pytest.mark.parametrize("carrier", ["grapple", "condition"])
def test_invalid_carriers_are_rejected_by_both_contracts(carrier):
    source = row("bandit")
    action = source["attacks"][0]
    if carrier == "grapple":
        action["properties"] = ["grapple"]
    else:
        action.update(applies_condition="unknown", save="DEX", dc=12)
    assert validate_creature_stat_block(source)
    with pytest.raises(ValueError, match=r"attacks\[0\]"):
        translate(source)


def test_structured_command_recharge_contract():
    source = row("ashmark_sergeant")
    source["actives"][0]["recharge"] = {"kind": "round", "uses": 1}
    assert validate_creature_stat_block(source) == []
    narrative = copy.deepcopy(source)
    del narrative["actives"][0]["kind"]
    assert validate_creature_stat_block(narrative)
    source["actives"][0]["recharge"]["uses"] = 0
    assert validate_creature_stat_block(source)


def test_special_text_does_not_drive_actions():
    source = row("hollow_mawling")
    before = translate(source)["action_pool"]
    changed = copy.deepcopy(source)
    for action in changed["attacks"]:
        action["special"] = "Everything explodes and heals."
    after = translate(changed)["action_pool"]
    for a, b in zip(before, after, strict=True):
        assert {k: v for k, v in a.items() if k != "special"} == {k: v for k, v in b.items() if k != "special"}


def test_unknown_attribute_fails_with_identity():
    source = row("bandit")
    source["attributes"]["LUCK"] = 10
    with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137.*attributes.*LUCK"):
        translate(source)


def test_zero_flat_damage_cannot_pass_usable_attack_floor():
    source = row("bandit")
    source["attacks"] = [{**source["attacks"][0], "damage": "00"}]
    source["actives"] = []
    with pytest.raises(ValueError, match=r"bandit.*enc137.*enemy137.*no usable damaging attack"):
        translate(source)


def test_structured_save_action_contract():
    from action_contracts import validate_action_extensions

    action = {
        "name": "Memory Scream",
        "kind": "attack",
        "resolution": "save",
        "damage": "3d8",
        "damage_type": "psychic",
        "save": "WIS",
        "dc": 18,
        "reach": 60,
        "type": "area",
        "save_success_damage": "none",
        "conditions_on_failure": [{"applies_condition": "stunned", "duration": 1}],
        "conditions_on_success": [],
    }
    validate_action_extensions(action, "scream")
    for mutation in (
        {"resolution": "bogus"},
        {"save": "BAD"},
        {"dc": True},
        {"save_success_damage": "full"},
        {"conditions_on_success": [{"applies_condition": "unknown", "duration": 1}]},
        {"conditions_on_failure": [{"applies_condition": "stunned", "duration": 0}]},
        {"conditions_on_failure": [{"applies_condition": "stunned", "duration": 1, "unknown": True}]},
    ):
        with pytest.raises(ValueError):
            validate_action_extensions({**action, **mutation}, "scream")


def test_structured_shared_public_contract_corpus():
    import json
    from pathlib import Path

    from combat_init_validation import validate_enemy_action_shapes
    from encounter_actions import validate_encounter_actions

    root = Path(__file__).resolve().parents[3] / "packages/shared/fixtures"
    corpus = json.loads((root / "creature_blocks.json").read_text())
    ids = json.loads((root / "creature_contract_case_ids.json").read_text())
    for polarity in ("valid", "invalid"):
        cases = [c for c in corpus[polarity] if c["name"].startswith(("structured_save_", "choir_"))]
        assert cases and {c["name"] for c in cases} == {
            n for n in ids[polarity] if n.startswith(("structured_save_", "choir_"))
        }
        assert len(cases) == len({c["name"] for c in cases})
        for case in cases:
            enemy = {
                "id": "fixture",
                "action_pool": [*case["block"]["attacks"], *case["block"]["actives"], *case["block"]["reactions"]],
            }
            if polarity == "valid":
                assert validate_creature_stat_block(case["block"]) == []
                validate_enemy_action_shapes([enemy])
                validate_encounter_actions([enemy])
            else:
                assert validate_creature_stat_block(case["block"]) == case["expected"]
                for validate in (validate_enemy_action_shapes, validate_encounter_actions):
                    with pytest.raises(ValueError):
                        validate([enemy])


@pytest.mark.parametrize("role", ["standard", "minion", "elite", "boss", "named"])
def test_choir_named_translation_preserves_authored_stats(role):
    enemy = translate(next(r for r in catalog() if r["id"] == "hollow_choir"), role=role)
    assert (enemy["hp"], enemy["ac"], enemy["damage_mult"], enemy["dc_mod"], enemy["attack_mod"]) == (200, 18, 1, 0, 0)
    actions = {a["name"]: a for a in enemy["action_pool"]}
    assert set(actions) == {"Memory Scream", "Dissonant Chord", "Cacophony", "Stolen Melody", "Silence Void"}
    assert actions["Memory Scream"]["resolution"] == "save"
    assert enemy["choir_reaction"]["kind"] == "spell_redirect"


@pytest.mark.parametrize("species", ["hollow_still", "hollow_architect", "hollow_unknown"])
def test_still_architect_unknown_named_refused(species):
    source = copy.deepcopy(
        next(r for r in catalog() if r["id"] == ("hollow_choir" if species == "hollow_unknown" else species))
    )
    source["id"] = species
    with pytest.raises(ValueError, match="Named/custom"):
        translate(source)
