"""Sneak Attack reaches persisted combat, narration, and the dice event."""

import json
import random
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _dice_events, _resolve_round
from combat.test_damage_affinity import catalog_fight as catalog_fight
from combat.test_damage_affinity import declare_weapon
from combat.test_spell_damage_lands import load_combat, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant

import combat_turn
from check_resolution_attack import resolve_attack
from declaration_payloads import AbilityDecl, DefendDecl


@pytest.fixture
async def rogue_fight(catalog_fight, spell_fight, dev_db_pool):
    await dev_db_pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{class}','\"rogue\"') WHERE player_id=$1",
        spell_fight.userdata.player_id,
    )
    ctx = await catalog_fight("bandit")
    state = ctx.userdata.combat_state
    actor = participant(state, ctx.userdata.player_id)
    actor.level = 1
    actor.initiative = 30
    target = participant(state, "foe")
    target.hp_current = target.hp_max = 200
    target.damage_affinities = {}
    return ctx


def damage_roll(notation, **kwargs):
    return SimpleNamespace(total=5 if notation == "1d8" else 3 * int(notation.split("d")[0]))


async def finish(ctx, faces=None):
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(n) for n in faces])
        if faces
        else patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
    ):
        result = await _resolve_round(ctx)
    return next(p for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)


async def test_weapon_damage_is_persisted_and_reported_once_per_round(rogue_fight):
    ctx = rogue_fight
    actor = participant(ctx.userdata.combat_state, ctx.userdata.player_id)
    assert actor.archetype_id == "rogue"
    actor.action_pool[0]["advantage"] = True
    actor.enhancers = ["extra_attack"]
    await declare_weapon(ctx)
    packet = await finish(ctx)
    assert packet["damage"] == 13
    assert packet["sneak_attack_dice"] == "1d6"
    assert packet["sneak_attack_raw_damage"] == 3
    events = [e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name]
    assert [e["damage"] for e in events] == [8, 5]
    assert events[0]["sneak_attack_dice"] == "1d6"
    assert events[0]["sneak_attack_raw_damage"] == 3
    assert events[0]["damage_type"] == "slashing"
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(state, "foe").hp_current == 187
    assert participant(state, actor.id).sneak_attack_round == 1
    ctx.userdata.combat_state = state
    await declare_weapon(ctx)
    await finish(ctx)
    assert participant(await load_combat(state.combat_id), "foe").hp_current == 174


@pytest.mark.parametrize(
    "level,count", [(1, 1), (4, 1), (5, 2), (8, 2), (9, 3), (12, 3), (13, 4), (16, 4), (17, 5), (20, 5)]
)
def test_level_dice(level, count):
    data = {"level": level, "sneak_attack_available": True, "conditions": []}
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
    ):
        result = resolve_attack(data, {"damage": "1d8", "advantage": True}, 10, 200, rng=random.Random(1))
    assert result.sneak_attack_dice == f"{count}d6"
    assert result.damage == 5 + 3 * count


async def test_precise_strike_real_activation_and_next_attack_only(rogue_fight):
    ctx = rogue_fight
    state = ctx.userdata.combat_state
    pid = ctx.userdata.player_id
    stamina = (await saved_player(pid))["stamina"]["current"]
    await combat_turn.declare_phase(
        ctx,
        [
            AbilityDecl(kind="ability", actor_id=pid, action="rogue_precise_strike", targets=[], argument_type=""),
            DefendDecl(kind="defend", actor_id="foe"),
        ],
    )
    packet = await finish(ctx)
    assert packet["resolved"]
    assert packet["condition_applied"] == "precise_strike"
    assert (await saved_player(pid))["stamina"]["current"] == stamina - 3
    state = await load_combat(state.combat_id)
    assert participant(state, "foe").hp_current == 200
    assert any(c["type"] == "precise_strike" and c["duration"] is None for c in participant(state, pid).conditions)
    ctx.userdata.combat_state = state
    await declare_weapon(ctx)
    packet = await finish(ctx, [2, 15])
    assert packet["roll"] == 15
    assert packet["damage"] == 8
    assert packet["sneak_attack_dice"] == "1d6"
    state = await load_combat(state.combat_id)
    assert not any(c["type"] == "precise_strike" for c in participant(state, pid).conditions)
    ctx.userdata.combat_state = state
    await declare_weapon(ctx)
    packet = await finish(ctx, [2])
    assert packet["roll"] == 2
    assert not packet["hit"]
    assert packet["sneak_attack_dice"] is None


@pytest.mark.parametrize(
    "kind,offset,fallen,dead,expected",
    [
        ("companion", (0, 3, 4), False, False, 8),
        ("companion", (0, 6, 8), False, False, 5),
        ("player", (0, 3, 4), False, False, 8),
        ("enemy", (0, 3, 4), False, False, 5),
        ("companion", (0, 3, 4), True, False, 5),
        ("player", (0, 3, 4), False, True, 5),
        ("none", (0, 0, 0), False, False, 5),
    ],
)
async def test_ally_geometry(rogue_fight, kind, offset, fallen, dead, expected):
    from session_data import CombatParticipant

    ctx = rogue_fight
    state = ctx.userdata.combat_state
    if kind != "none":
        state.participants.append(
            CombatParticipant(
                id="nearby",
                name="Nearby",
                type=kind,
                initiative=0,
                hp_current=20,
                hp_max=20,
                ac=10,
                is_fallen=fallen,
                is_dead=dead,
            )
        )
        state.spatial["positions"]["nearby"] = dict(
            zip(("x", "y", "z"), (5 + offset[0], offset[1], offset[2]), strict=True)
        )
        state.spatial["speeds"]["nearby"] = 30
    await declare_weapon(ctx)
    assert (await finish(ctx))["damage"] == expected


@pytest.mark.parametrize("trait,expected", [("resistant", 4), ("immune", 0), ("none", 8)])
async def test_combined_weapon_affinity_and_immune_spend(rogue_fight, trait, expected):
    ctx = rogue_fight
    state = ctx.userdata.combat_state
    actor = participant(state, ctx.userdata.player_id)
    actor.action_pool[0]["advantage"] = True
    actor.enhancers = ["extra_attack"]
    target = participant(state, "foe")
    target.damage_affinities = {trait: ["slashing"]} if trait != "none" else {}
    await declare_weapon(ctx)
    packet = await finish(ctx)
    first, second = packet["attacks"]
    assert (first["damage"], first["damage_type"], first["sneak_attack_dice"], first["sneak_attack_raw_damage"]) == (
        expected,
        "slashing",
        "1d6",
        3,
    )
    assert second["sneak_attack_dice"] is None
    events = [e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name]
    assert events[0]["damage"] == expected
    assert events[0]["sneak_attack_raw_damage"] == 3
    loaded = await load_combat(state.combat_id)
    assert participant(loaded, "foe").hp_current == 200 - expected - second["damage"]
    assert participant(loaded, actor.id).sneak_attack_round == 1


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("miss_then_hit", 8),
        ("critical", 16),
        ("target_advantage", 8),
        ("canceled", 5),
        ("nonrogue", 5),
    ],
)
async def test_attack_modes_and_miss_allowance(rogue_fight, mode, expected):
    ctx = rogue_fight
    state = ctx.userdata.combat_state
    actor = participant(state, ctx.userdata.player_id)
    actor.action_pool[0]["advantage"] = mode != "target_advantage"
    if mode == "target_advantage":
        participant(state, "foe").conditions = [{"type": "restrained", "source": "test", "duration": None}]
    if mode == "canceled":
        actor.conditions = [{"type": "blinded", "source": "test", "duration": None}]
    if mode == "nonrogue":
        actor.archetype_id = "warrior"
    if mode == "miss_then_hit":
        actor.enhancers = ["extra_attack"]
    await declare_weapon(ctx)
    faces = [1, 1, 15, 15] if mode == "miss_then_hit" else [20, 20] if mode == "critical" else None
    packet = await finish(ctx, faces)
    assert packet["damage"] == expected
    if mode == "miss_then_hit":
        assert [p["sneak_attack_dice"] for p in packet["attacks"]] == [None, "1d6"]
    if mode == "critical":
        assert packet["sneak_attack_dice"] == "2d6"


async def test_held_reload_keeps_allowance_and_does_not_replay(rogue_fight, dev_db_pool):
    from sample_fixtures import make_context

    import db_mutations
    from combat_support import _resolve_attack_packet

    ctx = rogue_fight
    state = ctx.userdata.combat_state
    pid = ctx.userdata.player_id
    actor = participant(state, pid)
    actor.action_pool[0]["advantage"] = True
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "attack", "action": "Longsword", "target_id": "foe"},
            "foe": {"type": "attack", "action": "Short Sword", "target_id": pid},
        },
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
    ):
        raw = await combat_turn._resolve_phase_impl(ctx)
        assert isinstance(raw, str)
        result = json.loads(raw)
    assert result["next"]["phase"] == "narration"
    loaded = await load_combat(state.combat_id)
    assert loaded.round_number == 1 and loaded.held_actions
    assert participant(loaded, "foe").hp_current == 192
    actor = participant(loaded, pid)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
    ):
        second = await _resolve_attack_packet(
            ctx.userdata,
            actor,
            actor.action_pool[0],
            participant(loaded, "foe"),
            combat_state=loaded,
            conn=dev_db_pool,
        )
    assert second["damage"] == 5 and second["sneak_attack_dice"] is None
    await db_mutations.save_combat_state(loaded.combat_id, loaded.to_dict(), conn=dev_db_pool)
    ctx = make_context(pid, room=ctx.userdata.room)
    ctx.userdata.combat_state = await load_combat(loaded.combat_id)
    count = len([e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", side_effect=damage_roll),
    ):
        await _resolve_round(ctx)
    assert participant(await load_combat(loaded.combat_id), "foe").hp_current == 187
    assert len([e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name]) == count
    await declare_weapon(ctx)
    assert (await finish(ctx))["sneak_attack_dice"] == "1d6"


async def test_legacy_player_snapshot_refused(rogue_fight):
    from session_data import CombatState

    data = rogue_fight.userdata.combat_state.to_dict()
    del next(p for p in data["participants"] if p["type"] == "player")["archetype_id"]
    with pytest.raises(ValueError, match="missing archetype_id: reset/reseed old snapshots"):
        CombatState.from_dict(data)


async def test_spell_attack_does_not_spend_weapon_allowance(rogue_fight):
    from combat.test_spell_damage_lands import declare_spell, prepare_spell

    ctx = rogue_fight
    actor = participant(ctx.userdata.combat_state, ctx.userdata.player_id)
    actor.action_pool[0]["advantage"] = True
    actor.conditions = [{"type": "precise_strike", "source": "rogue_precise_strike", "duration": None}]
    await prepare_spell(ctx, "arcane_bolt")
    await declare_spell(ctx)
    packet = (await finish(ctx))["cast"]["damage_result"]
    assert packet["sneak_attack_dice"] is None
    loaded = await load_combat(ctx.userdata.combat_state.combat_id)
    actor = participant(loaded, actor.id)
    assert actor.sneak_attack_round is None
    assert not any(c["type"] == "precise_strike" for c in actor.conditions)
