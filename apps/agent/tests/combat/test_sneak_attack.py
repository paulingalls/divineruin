from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die, _dice_events, _resolve_round
from combat.test_damage_affinity import catalog_fight as catalog_fight
from combat.test_damage_affinity import declare_weapon
from combat.test_spell_damage_lands import load_combat, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from sample_fixtures import make_context
from voice_condition_fixtures import participant

import combat_turn
import db_mutations
from combat_support import _resolve_attack_packet


@contextmanager
def rolls(faces=(15,)):
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(n) for n in faces]),
        patch(
            "check_resolution_attack.dice_roll",
            side_effect=lambda s, **kw: _damage_die(5 if s == "1d8" else 3 * int(s.split("d")[0])),
        ),
    ):
        yield


@pytest.fixture
async def rogue_fight(catalog_fight, spell_fight, dev_db_pool):
    pid = spell_fight.userdata.player_id
    await dev_db_pool.execute("UPDATE players SET data=jsonb_set(data,'{class}','\"rogue\"') WHERE player_id=$1", pid)
    ctx = await catalog_fight("bandit")
    state = ctx.userdata.combat_state
    actor, target = participant(state, ctx.userdata.player_id), participant(state, "foe")
    actor.level, actor.initiative = 1, 30
    target.hp_current = target.hp_max = 200
    target.damage_affinities = {}
    return ctx, actor, target


async def finish(ctx, faces=(15,)):
    with rolls(faces):
        result = await _resolve_round(ctx)
    return next(p for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)


@pytest.mark.parametrize("trait,expected", [("resistant", 4), ("immune", 0), ("none", 8)])
async def test_weapon_affinity_packets_and_once_per_round(rogue_fight, trait, expected):
    ctx, actor, target = rogue_fight
    actor.action_pool[0]["advantage"], actor.enhancers = True, ["extra_attack"]
    target.damage_affinities = {trait: ["slashing"]} if trait != "none" else {}
    await declare_weapon(ctx)
    first, second = (await finish(ctx, (15, 15, 15, 15)))["attacks"]
    assert (first["damage"], first["sneak_attack_dice"], first["sneak_attack_raw_damage"]) == (expected, "1d6", 3)
    assert (second["damage"], second["sneak_attack_dice"]) == ({"none": 5, "resistant": 2, "immune": 0}[trait], None)
    events = [e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name]
    assert [e["damage"] for e in events] == [expected, second["damage"]]
    assert events[0]["damage_type"] == first["damage_type"] == "slashing"
    assert (events[0]["sneak_attack_dice"], events[0]["sneak_attack_raw_damage"]) == ("1d6", 3)
    loaded = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(loaded, "foe").hp_current == 200 - expected - second["damage"]


@pytest.mark.parametrize(
    "kind,offset,fallen,dead,level,expected",
    [
        ("companion", (0, 3, 4), False, False, 1, 8),
        ("companion", (0, 6, 8), False, False, 1, 5),
        ("player", (0, 3, 4), False, False, 5, 11),
        ("player", (0, 3, 4), False, False, 9, 14),
        ("player", (0, 3, 4), False, False, 13, 17),
        ("player", (0, 3, 4), False, False, 17, 20),
        ("enemy", (0, 3, 4), False, False, 1, 5),
        ("companion", (0, 3, 4), True, False, 1, 5),
        ("player", (0, 3, 4), False, True, 1, 5),
        ("none", (0, 0, 0), False, False, 1, 5),
    ],
)
async def test_ally_geometry(rogue_fight, kind, offset, fallen, dead, level, expected):
    ctx, actor, target = rogue_fight
    state = ctx.userdata.combat_state
    actor.level = level
    if kind != "none":
        state.participants.append(replace(target, id="nearby", type=kind, is_fallen=fallen, is_dead=dead))
        state.spatial["positions"]["nearby"] = dict(
            zip(("x", "y", "z"), (5 + offset[0], offset[1], offset[2]), strict=True)
        )
        state.spatial["speeds"]["nearby"] = 30
    await declare_weapon(ctx)
    assert (await finish(ctx))["damage"] == expected


async def test_precise_strike_and_held_reload(rogue_fight, dev_db_pool):
    ctx, actor, _ = rogue_fight
    pid, combat_id = actor.id, ctx.userdata.combat_state.combat_id
    stamina = (await saved_player(pid))["stamina"]["current"]
    await combat_turn._declare_phase_impl(
        ctx, {pid: {"type": "ability", "action": "rogue_precise_strike"}, "foe": {"type": "defend"}}
    )
    assert (await finish(ctx))["condition_applied"] == "precise_strike"
    assert (await saved_player(pid))["stamina"]["current"] == stamina - 3
    ctx.userdata.combat_state = await load_combat(combat_id)
    assert participant(ctx.userdata.combat_state, "foe").hp_current == 200
    await combat_turn._declare_phase_impl(
        ctx,
        {
            pid: {"type": "attack", "action": "Longsword", "target_id": "foe"},
            "foe": {"type": "attack", "action": "Short Sword", "target_id": pid},
        },
    )
    with rolls((2, 15)):
        await combat_turn._resolve_phase_impl(ctx)
    loaded = await load_combat(combat_id)
    actor = participant(loaded, pid)
    assert loaded.round_number == 2 and loaded.held_actions
    assert participant(loaded, "foe").hp_current == 192
    assert not any(c["type"] == "precise_strike" for c in actor.conditions)
    with rolls((2,)):
        miss = await _resolve_attack_packet(
            ctx.userdata, actor, actor.action_pool[0], participant(loaded, "foe"), combat_state=loaded, conn=dev_db_pool
        )
    assert miss["roll"] == 2 and not miss["hit"]
    actor.action_pool[0]["advantage"] = True
    with rolls((15, 15)):
        second = await _resolve_attack_packet(
            ctx.userdata, actor, actor.action_pool[0], participant(loaded, "foe"), combat_state=loaded, conn=dev_db_pool
        )
    assert second["damage"] == 5 and second["sneak_attack_dice"] is None
    await db_mutations.save_combat_state(combat_id, loaded.to_dict(), conn=dev_db_pool)
    ctx = make_context(pid, room=ctx.userdata.room)
    ctx.userdata.combat_state = await load_combat(combat_id)
    count = len([e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name])
    with rolls((15,)):
        await _resolve_round(ctx)
    assert participant(await load_combat(combat_id), "foe").hp_current == 187
    assert len([e for e in _dice_events(ctx.userdata.room) if e.get("attacker") == actor.name]) == count
    await declare_weapon(ctx)
    assert (await finish(ctx, (15, 15)))["sneak_attack_dice"] == "1d6"
