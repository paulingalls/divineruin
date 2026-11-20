"""Declarations land typed damage once, and persist the final HP and DM packet."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from combat.test_spell_damage_lands import declare_spell, load_combat, prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant

import combat_init
import combat_turn
import db_mutations
from declaration_payloads import AttackDecl, DefendDecl


@pytest.fixture
async def catalog_fight(spell_fight, dev_db_pool):
    ctx = spell_fight
    original = ctx.userdata.combat_state.combat_id
    created = []

    async def start(creature_id, weapon=None):
        template_id = f"affinity_{uuid4().hex}"
        template = {
            "id": template_id,
            "name": "Affinity fight",
            "recommended_party_level": 8,
            "difficulty": "moderate",
            "enemies": [
                {"id": "foe", "creature_id": creature_id, "role": "standard"},
                {"id": "survivor", "creature_id": "bandit", "role": "standard"},
            ],
            "scene_placement": {
                "party_start": {"x": 0, "y": 0, "z": 0},
                "companion_start": {"x": 0, "y": 5, "z": 0},
                "actors": {"foe": {"x": 5, "y": 0, "z": 0}, "survivor": {"x": 20, "y": 0, "z": 0}},
                "locations": {},
                "zones": {},
            },
        }
        await dev_db_pool.execute(
            "INSERT INTO encounter_templates(id,data) VALUES($1,$2::jsonb)", template_id, json.dumps(template)
        )
        await dev_db_pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{equipment}', $2::jsonb) WHERE player_id=$1",
            ctx.userdata.player_id,
            json.dumps(
                {
                    "main_hand": weapon
                    or {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}
                }
            ),
        )
        ctx.userdata.combat_state = None
        await combat_init._start_combat_impl(ctx, template_id, "A foe approaches.")
        entered = ctx.userdata.combat_state
        assert entered is not None
        state = await load_combat(entered.combat_id)
        created.append((template_id, state.combat_id))
        ctx.userdata.combat_state = state
        state.terrain = "forest"
        actor = participant(state, ctx.userdata.player_id)
        actor.attributes = {"intelligence": 10, "wisdom": 10, "strength": 10, "dexterity": 10}
        actor.level = 8
        return ctx

    yield start
    for template_id, combat_id in created:
        await db_mutations.delete_combat_state(combat_id, conn=dev_db_pool)
        await dev_db_pool.execute("DELETE FROM encounter_templates WHERE id=$1", template_id)
    ctx.userdata.combat_state = await load_combat(original)


async def resolve(ctx, *, face=15, raw=5, no_save=False):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=raw)),
        patch("dice.roll", return_value=SimpleNamespace(total=raw)),
        patch("check_resolution_save.roll_participant_save", side_effect=AssertionError("plant must not save"))
        if no_save
        else nullcontext(),
    ):
        result = await _resolve_round(ctx)
    return next(p for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)


async def declare_weapon(ctx):
    await combat_turn.declare_phase(
        ctx,
        [
            AttackDecl(
                reshape=[],
                kind="attack",
                actor_id=ctx.userdata.player_id,
                action="Longsword",
                target_id="foe",
                held_item_id="",
                rider="",
            ),
            DefendDecl(reshape=[], kind="defend", actor_id="foe"),
        ],
    )


@pytest.mark.parametrize("path", ["weapon", "attack_spell", "save_spell"])
@pytest.mark.parametrize("trait,expected", [("vulnerable", 10), ("resistant", 2), ("immune", 0), ("unmatched", 5)])
async def test_typed_damage_packet_and_hp(catalog_fight, dev_db_pool, path, trait, expected):
    ctx = await catalog_fight("hollow_weaver")
    state = ctx.userdata.combat_state
    target = participant(state, "foe")
    assert target.damage_affinities["vulnerable"] == ["slashing", "piercing", "bludgeoning", "radiant"]
    assert target.damage_affinities["immune"] == ["poison"]
    dtype = {"weapon": "slashing", "attack_spell": "force", "save_spell": "cold"}[path]
    target.damage_affinities = {"resistant": [], "immune": [], "vulnerable": []}
    target.damage_affinities[trait if trait != "unmatched" else "immune"] = [dtype if trait != "unmatched" else "acid"]
    target.conditions = [{"type": "charmed", "source": ctx.userdata.player_id, "duration": 3}]
    hp = target.hp_current
    if path == "weapon":
        await declare_weapon(ctx)
    else:
        spell_id = "arcane_bolt" if path == "attack_spell" else "arcane_elemental_burst"
        await prepare_spell(ctx, spell_id)
        await declare_spell(ctx, spell_id, "cold")
    packet = await resolve(ctx, face=1 if path == "save_spell" else 15)
    damage = packet if path == "weapon" else packet["cast"]["damage_result"]
    assert damage["damage"] == expected
    loaded = await load_combat(state.combat_id)
    victim = participant(loaded, "foe")
    assert victim.hp_current == hp - expected
    assert any(c["type"] == "charmed" for c in victim.conditions) == (expected == 0)
    if "damage_components" in damage:
        assert [c["damage"] for c in damage["damage_components"]] == [expected]


@pytest.mark.parametrize(
    "tagged,face,resonance,expected", [(True, 1, 0, 32), (True, 1, 6, 40), (False, 1, 0, 7), (False, 20, 0, 3)]
)
async def test_blight_plant_maximum_without_save(catalog_fight, dev_db_pool, tagged, face, resonance, expected):
    ctx = await catalog_fight("corrupted_treant")
    state = ctx.userdata.combat_state
    target = participant(state, "foe")
    assert target.tags == ["plant"]
    target.tags = ["plant"] if tagged else []
    target.hp_current = 31 if tagged else target.hp_current
    hp = target.hp_current
    ctx.userdata.resonance.current = resonance
    await dev_db_pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{resonance}', $2::jsonb) WHERE player_id=$1",
        ctx.userdata.player_id,
        json.dumps({"current": resonance}),
    )
    await prepare_spell(ctx, "primal_blight")
    before = await saved_player(ctx.userdata.player_id)
    await declare_spell(ctx, "primal_blight")
    packet = await resolve(ctx, face=face, raw=7, no_save=tagged)
    cast = packet["cast"]
    damage = cast["damage_result"]
    assert damage["damage"] == expected
    assert ("save" in damage) != tagged
    if tagged:
        assert damage["damage_components"][0]["dice"] == ("4d8" if resonance == 0 else "5d8")
    loaded = await load_combat(state.combat_id)
    victim = participant(loaded, "foe")
    assert victim.hp_current == max(0, hp - expected)
    assert victim.is_fallen == tagged
    after = await saved_player(ctx.userdata.player_id)
    assert after["focus"]["current"] < before["focus"]["current"]


async def test_ice_storm_keeps_component_types(catalog_fight):
    ctx = await catalog_fight("corrupted_treant")
    state = ctx.userdata.combat_state
    hp = participant(state, "foe").hp_current
    await prepare_spell(ctx, "primal_ice_storm")
    await declare_spell(ctx, "primal_ice_storm")
    packet = await resolve(ctx, face=1, raw=5)
    damage = packet["cast"]["damage_result"]
    assert [(c["damage_type"], c["damage"]) for c in damage["damage_components"]] == [("bludgeoning", 2), ("cold", 5)]
    assert damage["damage"] == 7
    assert participant(await load_combat(state.combat_id), "foe").hp_current == hp - 7


@pytest.mark.parametrize("path", ["weapon", "spell"])
async def test_shared_hollow_poison_immunity(catalog_fight, monkeypatch, path):
    from copy import deepcopy
    from dataclasses import replace

    import spells

    ctx = await catalog_fight("hollow_weaver")
    state = ctx.userdata.combat_state
    hp = participant(state, "foe").hp_current
    if path == "weapon":
        participant(state, ctx.userdata.player_id).action_pool[0]["damage_type"] = "poison"
        await declare_weapon(ctx)
    else:
        # No authored poison spell exists; retain the real cast contract with a typed test profile.
        original = spells.get_spell("arcane_bolt")
        assert original.combat_damage is not None
        profile = deepcopy(original.combat_damage)
        profile["components"][0]["damage_type"] = "poison"
        monkeypatch.setitem(spells._spells, original.id, replace(original, combat_damage=profile))
        await declare_spell(ctx)
    packet = await resolve(ctx)
    damage = packet if path == "weapon" else packet["cast"]["damage_result"]
    assert damage["damage"] == 0
    assert participant(await load_combat(state.combat_id), "foe").hp_current == hp


@pytest.mark.parametrize("face,expected", [(1, 0), (20, 1)])
async def test_miss_and_successful_half_save_with_resistance(catalog_fight, face, expected):
    ctx = await catalog_fight("corrupted_treant")
    state = ctx.userdata.combat_state
    target = participant(state, "foe")
    hp = target.hp_current
    if face == 1:
        await declare_spell(ctx)
    else:
        await prepare_spell(ctx, "primal_ice_storm")
        await declare_spell(ctx, "primal_ice_storm")
    damage = (await resolve(ctx, face=face, raw=7))["cast"]["damage_result"]
    if face == 20:
        assert [c["damage"] for c in damage["damage_components"]] == [1, 3]
        assert damage["save"]["success"]
        expected = 4
    assert damage["damage"] == expected
    assert participant(await load_combat(state.combat_id), "foe").hp_current == hp - expected


async def test_bonus_rider_uses_its_own_type(catalog_fight):
    import conditions

    ctx = await catalog_fight("corrupted_treant")
    state = ctx.userdata.combat_state
    actor = participant(state, ctx.userdata.player_id)
    actor.conditions = conditions.apply_condition([], "temporary_hollowed", source="test")
    target = participant(state, "foe")
    target.damage_affinities = {"immune": [], "resistant": ["slashing"], "vulnerable": ["necrotic"]}
    hp = target.hp_current
    await declare_weapon(ctx)
    damage = await resolve(ctx, raw=5)
    # Raw base 5 and raw necrotic rider 5 must be adjusted independently.
    assert (damage["damage"], damage["bonus_damage"], damage["bonus_damage_type"]) == (12, 10, "necrotic")
    assert participant(await load_combat(state.combat_id), "foe").hp_current == hp - 12


async def test_held_roll_reload_lands_affinity_once():
    from combat._helpers import _call, _ctx_at_resolution, _resolve_deps

    from session_data import CombatState

    ctx = _ctx_at_resolution(player_hp=25, enemy_hp=100, reaction_ids=("skirmisher_sidestep", "rogue_uncanny_dodge"))
    participant(ctx.userdata.combat_state, "player_1").damage_affinities = {"vulnerable": ["slashing"]}
    deps = _resolve_deps(damage=5)
    for _ in range(3):
        await _call(ctx, deps)
    state = ctx.userdata.combat_state
    raw = state.held_actions[0]["roll"].copy()
    assert raw["attack_result"]["damage"] == 5
    ctx.userdata.combat_state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    packet = await _call(ctx, deps)
    assert participant(ctx.userdata.combat_state, "player_1").hp_current == 15
    assert any(p.get("damage") == 10 for p in packet["packets"])


@pytest.mark.parametrize("trait,hp,killed", [("resistant", 4, False), ("vulnerable", 8, True)])
async def test_killing_blow_context_follows_adjusted_damage(catalog_fight, trait, hp, killed):
    ctx = await catalog_fight("hollow_weaver")
    target = participant(ctx.userdata.combat_state, "foe")
    target.damage_affinities = {"resistant": [], "immune": [], "vulnerable": []}
    target.damage_affinities[trait] = ["slashing"]
    target.hp_current = hp
    await declare_weapon(ctx)
    packet = await resolve(ctx)
    assert (packet["context"] == "killing_blow") is killed
    assert packet["target_fallen"] is killed
