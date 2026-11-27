"""Saved Fate rolls and reaction attack receipts for spell marks."""

import json
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20, _damage_die, _resolve_round
from acceptance._spell_hostile_condition_helpers import add_player, attack, cast_spell, play, receipt, reload, set_foe
from acceptance.test_martial_core_kit import warriors as warriors
from acceptance.test_opportunity_strike import MOVER, STRIKE, activate_as
from acceptance.test_opportunity_strike import fight as fight
from acceptance.test_self_buff_electives import enter_bandit_fight
from acceptance.test_spell_marks import (
    BOLT,
    GUIDING,
    INVISIBILITY,
    INVISIBLE,
    MARK,
    context,
    has,
    mark_fight,
    skill_face,
    swing,
)
from acceptance.test_spell_marks import dev_db_pool as dev_db_pool
from acceptance.test_spell_marks import spell_fight as spell_fight
from acceptance.test_spell_new_conditions import slow
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_vanish import walk as walk
from combat.test_spell_damage_lands import saved_player
from livekit.agents import ToolError
from voice_condition_fixtures import participant, spatial_record
from weapon_fixtures import DAGGER

import character_spells
import combat_turn
import db
import db_mutations
from activate_tools import activate
from combat_structures import add_wall
from session_data import SessionData


@pytest.mark.parametrize("spell", [False, True])
async def test_marked_attack_resumes_once_after_fate(spell_fight, spell):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    mage = await add_player(ctx, "mage", (INVISIBILITY,))
    await play(ctx, cast_spell(mage, INVISIBILITY, ally), cast_spell(caster, GUIDING))
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
        ally,
        '{"patron":"zhael","level":40,"max":100}',
    )
    before = await saved_player(ally)
    declaration = cast_spell(ally, BOLT) if spell else attack(ally, DAGGER["name"], "foe")
    await combat_turn.declare_phase(ctx, [declaration])
    call = game_tools(ctx.userdata, combat_turn.resolve_phase, activate)
    with patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(17)]) as rolls:
        first = await call("resolve_phase")
        offer = first["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"]) == ("attack", ally)
        state = await reload(ctx)
        assert not has(state, "foe", MARK) and has(state, ally, INVISIBLE)
        assert participant(state, "foe").hp_current == 100
        party = ctx.userdata.party
        ctx.userdata = SessionData(
            player_id=ally, room=ctx.userdata.room, combat_state=state, location_id=ctx.userdata.location_id
        )
        ctx.userdata.party = party
        call = game_tools(ctx.userdata, combat_turn.resolve_phase, activate)
        with patch("check_resolution_attack.dice_roll", return_value=_damage_die(2)) as damage:
            resolved = await call("resolve_phase")
    if spell:
        cast = next(p["cast"] for p in resolved["packets"] if p["actor_id"] == ally)
        assert cast["condition_removed"] == INVISIBLE
        result = cast["damage_result"]
        assert result["attack_total"] == 23
    else:
        result = swing(resolved["packets"], ally)
        assert result["roll"] == 17 and result["condition_removed"] == INVISIBLE
    assert result["hit"]
    assert rolls.call_count == 2
    damage.assert_called_once()
    state = await reload(ctx)
    assert participant(state, "foe").hp_current == 100 - result["damage"]
    assert not has(state, ally, INVISIBLE)
    assert (await saved_player(ally))["focus"] == before["focus"]
    await _resolve_round(ctx)
    packets, _ = await play(ctx, attack(ally, DAGGER["name"], "foe"), faces=[3, 17])
    assert swing(packets, ally)["roll"] == 3


@pytest.mark.parametrize("fight", ["party"], indirect=True)
async def test_first_reaction_strike_spends_mark_for_all_later_strikes(fight):
    warrior, caster, other = fight.players
    first, second = sorted((warrior, other))
    await fight.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{focus,current}','10') WHERE player_id=$1", caster
    )
    for spell in (INVISIBILITY, GUIDING):
        await character_spells.record_learned(caster, spell, "discovery", conn=fight.pool)
    await fight.command("declare_phase", {"declarations": [cast_spell(caster, INVISIBILITY, first).model_dump()]})
    await fight.drain()
    state = await fight.reload()
    positions = spatial_record(state)["positions"]
    positions[MOVER]["x"] = 5
    positions[other]["x"] = 0
    participant(state, MOVER).hp_current = participant(state, MOVER).hp_max = 100
    await fight.persist()
    action = participant(state, MOVER).action_pool[0]["name"]
    await fight.command(
        "declare_phase",
        {"declarations": [cast_spell(caster, GUIDING, MOVER).model_dump(), attack(MOVER, action, caster).model_dump()]},
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(n) for n in (3, 17, 3, 17)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await fight.command("resolve_phase", {})
        departure = await fight.command("resolve_phase", {})
        window = departure["next"]["waiting_on"]
        assert window["stage"] == "movement"
        assert {r["actor_id"] for r in window["reactions"]} == {first, second}
        await activate_as(fight, first)
        await activate_as(fight, second)
        result = await fight.command("resolve_phase", {})
    strikes = [p for p in result["packets"] if p.get("reaction") == STRIKE]
    assert [(p["actor_id"], p["window_id"], p["roll"]) for p in strikes] == [
        (first, window["window_id"], 17),
        (second, window["window_id"], 3),
    ]
    assert strikes[0]["condition_removed"] == INVISIBLE and "condition_removed" not in strikes[1]
    state = await fight.reload()
    assert not has(state, first, INVISIBLE) and not has(state, MOVER, MARK)


async def test_an_attack_that_cannot_reach_leaves_the_mark(spell_fight):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    state = ctx.userdata.combat_state
    participant(state, caster).initiative = 30
    spatial_record(state)["positions"]["foe"]["x"] = 60
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    packets, state = await play(ctx, cast_spell(caster, GUIDING), attack(ally, DAGGER["name"], "foe"))
    assert not any("roll" in packet for packet in packets if packet["actor_id"] == ally)
    assert has(state, "foe", MARK)


@pytest.mark.parametrize("warriors", ["companion_kael"], indirect=True)
async def test_an_invisible_companion_reappears_when_it_attacks(warriors):
    caster = warriors.players[0]
    companion = warriors.sd.companion.id
    await warriors.pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{focus,current}','10') WHERE player_id=$1", caster
    )
    await character_spells.record_learned(caster, INVISIBILITY, "discovery", conn=warriors.pool)
    await warriors.command("enter_mode", {"mode": "combat", "encounter_id": warriors.encounter_id})
    state = await warriors.reload()
    foe = next(p.id for p in state.participants if not p.is_ally)
    actor = participant(state, companion)
    spatial_record(state)["positions"][foe] = spatial_record(state)["positions"][companion].copy()
    await warriors.persist()
    await warriors.command(
        "declare_phase", {"declarations": [cast_spell(caster, INVISIBILITY, companion).model_dump()]}
    )
    await warriors.drain()
    state = await warriors.reload()
    assert has(state, companion, INVISIBLE)
    await warriors.command(
        "declare_phase", {"declarations": [attack(companion, actor.action_pool[0]["name"], foe).model_dump()]}
    )
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        packets = await warriors.drain()
    assert swing(packets, companion)["condition_removed"] == INVISIBLE
    assert not has(await warriors.reload(), companion, INVISIBLE)


async def test_exploration_stealth_and_hostile_cast_use_saved_invisibility(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "mage", (BOLT, "arcane_prestidigitation"))
    explore = context(caster)
    explore.userdata.party = ctx.userdata.party
    ally_ctx = context(ally)
    assert await skill_face(ally_ctx, "stealth") == 3
    cast = json.loads(await activate(explore, INVISIBILITY, target_id=ally))
    assert cast["condition_applied"] == INVISIBLE
    assert await skill_face(ally_ctx, "stealth") == 17
    assert await skill_face(ally_ctx, "acrobatics") == 3
    await activate(ally_ctx, "arcane_prestidigitation")
    assert await skill_face(ally_ctx, "stealth") == 17
    cast = json.loads(await activate(ally_ctx, BOLT))
    assert cast["condition_removed"] == INVISIBLE
    assert (await saved_player(ally))["conditions"] == []
    assert await skill_face(ally_ctx, "stealth") == 3


async def test_exploration_invisibility_carries_into_a_real_encounter(walk):
    caster, ally = walk.players
    await walk.pool.execute("UPDATE players SET data=jsonb_set(data,'{focus,current}','10') WHERE player_id=$1", caster)
    await character_spells.record_learned(caster, INVISIBILITY, "discovery", conn=walk.pool)
    result = await walk.command("activate", {"id": INVISIBILITY, "target_id": ally})
    assert result["condition_applied"] == INVISIBLE
    foe = await enter_bandit_fight(walk)
    state = await walk.reload()
    assert has(state, ally, INVISIBLE)
    action = participant(state, foe).action_pool[0]["name"]
    await walk.command("declare_phase", {"declarations": [attack(foe, action, ally).model_dump()]})
    with patch("check_resolution.dice_roll", side_effect=[_d20(17), _d20(3)]):
        packets = await walk.drain()
    assert swing(packets, foe)["roll"] == 3


async def test_guiding_light_refuses_non_foes_before_declaring(spell_fight):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    state = ctx.userdata.combat_state
    add_wall(state, "wall", "Wall", {"x": 40, "y": -5, "z": 0}, {"x": 40, "y": 5, "z": 0})
    fallen = participant(state, "control")
    fallen.hp_current = 0
    fallen.is_fallen = fallen.is_dead = True
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = (await reload(ctx)).to_dict()
    for target in (ally, "wall", "control"):
        with pytest.raises(ToolError, match="standing enemy"):
            await combat_turn.declare_phase(ctx, [cast_spell(caster, GUIDING, target)])
        assert (await reload(ctx)).to_dict() == before


async def test_a_failed_slow_save_keeps_an_ally_invisible(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    mage = await add_player(ctx, "mage", (INVISIBILITY,))
    ally = await add_player(ctx, "mage")
    await set_foe(ctx)
    await play(ctx, cast_spell(mage, INVISIBILITY, ally))
    packets, _ = await play(ctx, slow(caster, ally), face=1)
    result = receipt(packets, caster)["condition_results"][0]
    assert (result["target_id"], result["save"]["success"]) == (ally, False)
    assert "condition_removed" not in result
    state = await reload(ctx)
    assert has(state, ally, "slowed") and has(state, ally, INVISIBLE)
