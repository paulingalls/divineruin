"""Condition-spell delivery and live declaration checks through saved phase packets."""

import json
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20, _enemy
from acceptance._catalog_cutover_helpers import started as started
from acceptance._spell_hostile_condition_helpers import (
    add_player,
    attack,
    cast_spell,
    defend,
    instance,
    play,
    receipt,
    reload,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos
from acceptance.test_architect_reaction import archers as archers
from acceptance.test_architect_reaction import cast, declare, forced_rolls, wall_raised
from acceptance.test_choir_encounter import search
from acceptance.test_spell_new_conditions import CROSSBOW, FIRE, SLOW, equip, move, slow
from combat.test_spell_damage_lands import prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant, spatial_record
from weapon_fixtures import DAGGER

import character_spells
import combat_recharge
import combat_turn
import db
from activate_tools import activate
from combat_structures import add_wall
from declaration_payloads import AbilityDecl, RetreatDecl


@pytest.mark.parametrize("retreat", [False, True])
async def test_live_slow_refuses_predeclared_cunning_action(spell_fight, retreat):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    rogue = await add_player(ctx, "rogue")
    await set_foe(ctx)
    await equip(ctx, rogue, DAGGER)
    spatial_record(ctx.userdata.combat_state)["positions"]["foe"]["x"] = 4
    origin = spatial_record(ctx.userdata.combat_state)["positions"][rogue].copy()
    row = await saved_player(rogue)
    pair = (
        RetreatDecl(kind="retreat", actor_id=rogue, rider="disengage")
        if retreat
        else (attack(rogue, DAGGER["name"], "foe", "hide"))
    )
    packets, state = await play(ctx, slow(caster, rogue), pair)
    assert receipt(packets, caster)["condition_targets"] == [rogue]
    refused = next(p for p in packets if p["actor_id"] == rogue)
    assert refused["resolved"] is False and "Slow" in refused["reason"]
    assert spatial_record(state)["positions"][rogue] == origin
    assert participant(state, "foe").hp_current == 100
    assert (await saved_player(rogue))["stamina"] == row["stamina"]
    if retreat:
        with pytest.raises(ToolError, match="Slow"):
            await combat_turn.declare_phase(ctx, [pair])
        packets, state = await play(ctx, RetreatDecl(kind="retreat", actor_id=rogue, rider=""))
        assert next(p for p in packets if p["actor_id"] == rogue and "destination" in p)["moved_ft"] == 15
        assert spatial_record(state)["positions"][rogue] != origin


async def test_slow_suppresses_only_its_targets_opportunity_attack(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await set_foe(ctx, foe_id="control")
    await set_foe(ctx)
    await play(ctx, slow(caster, "foe"))
    state = ctx.userdata.combat_state
    spatial_record(state)["positions"]["control"]["x"] = 20
    hp = participant(state, caster).hp_current
    await combat_turn.declare_phase(ctx, [move(caster, 15)])
    with patch("check_resolution.dice_roll", return_value=_d20(18)):
        resolved = json.loads(await combat_turn.resolve_phase(ctx))
    assert not any(p.get("opportunity_attack") for p in resolved["packets"])
    state = await reload(ctx)
    assert not state.reactions_available["foe"]["spent"]
    assert participant(state, caster).hp_current == hp
    assert spatial_record(state)["positions"][caster]["x"] == 15
    # Reload through wrap, then leave the unaffected Bandit's reach from the same distance.
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        while ctx.userdata.combat_state.beat != "declaration":
            await combat_turn.resolve_phase(ctx)
    await combat_turn.declare_phase(ctx, [move(caster, 30)])
    with patch("check_resolution.dice_roll", return_value=_d20(18)):
        resolved = json.loads(await combat_turn.resolve_phase(ctx))
    (strike,) = [p for p in resolved["packets"] if p.get("opportunity_attack")]
    assert strike["actor_id"] == "control" and strike["damage"] > 0
    state = await reload(ctx)
    assert state.reactions_available["control"]["spent"]
    assert participant(state, caster).hp_current == hp - strike["damage"]


async def test_partial_other_caster_hold_keeps_owner_and_continues(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (SLOW,))
    await set_foe(ctx, foe_id="second")
    await set_foe(ctx)
    _, held = await play(ctx, slow(caster, "foe"), defend(other))
    ours = [instance("slowed", SLOW, caster, "wis")]
    assert participant(held, "foe").conditions == ours
    packets, state = await play(ctx, defend(caster), slow(other, "foe", "second"))
    cast = receipt(packets, other)
    assert cast["condition_results"][0]["condition_outcome"] == "already_held"
    assert cast["condition_targets"] == ["second"]
    assert participant(state, "foe").conditions == ours
    assert participant(state, "second").conditions == [instance("slowed", SLOW, other, "wis")]
    assert (await saved_player(other))["concentration"]["spell_id"] == SLOW
    packets, state = await play(ctx, defend(caster), slow(other, "foe"))
    assert receipt(packets, other)["condition_targets"] == []
    assert participant(state, "foe").conditions == ours
    assert not participant(state, "second").conditions
    assert (await saved_player(other))["concentration"]["spell_id"] == SLOW


@pytest.mark.parametrize("spell", [FIRE, SLOW])
async def test_condition_save_resumes_each_recipient_once(spell_fight, spell):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, spell)
    for foe in ("foe", "second", "third"):
        await set_foe(ctx, foe_id=foe)
    for foe in ("foe", "second", "third"):
        spatial_record(ctx.userdata.combat_state)["positions"][foe]["x"] = 25
    pool = await db.get_pool()
    await pool.execute(
        """UPDATE players SET data=jsonb_set(data,'{divine_favor}','{"patron":"zhael","level":40,"max":100}')
           WHERE player_id=$1""",
        caster,
    )
    before = await saved_player(caster)
    declaration = slow(caster, "foe", "second", "third") if spell == SLOW else cast_spell(caster, FIRE)
    await combat_turn.declare_phase(ctx, [declaration])
    call = game_tools(ctx.userdata, combat_turn.resolve_phase, activate)
    with patch("check_resolution.dice_roll", side_effect=[_d20(n) for n in (1, 20, 1, 1, 1, 1)]):
        result = await call("resolve_phase")
        for target in ("foe", "second", "third"):
            offer = result["fate_offer"]
            assert offer["roller_id"] == target
            state = await reload(ctx)
            if target == "second":
                continuation = state.ally_continuation
                assert continuation is not None
                checkpoint = continuation["steps"]["spell_condition"]["results"]
                assert [(r["target_id"], r["save"]["roll"]) for r in checkpoint] == [("foe", 1)]
                assert participant(state, "foe").conditions
                assert not participant(state, target).conditions
            result = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
    cast = receipt(result["packets"], caster)
    assert [(r["target_id"], r["save"]["roll"]) for r in cast["condition_results"]] == [
        ("foe", 1),
        ("second", 20),
        ("third", 1),
    ]
    assert cast["condition_targets"] == ["foe", "third"]
    state = await reload(ctx)
    assert len(participant(state, "foe").conditions) == len(participant(state, "third").conditions) == 1
    assert not participant(state, "second").conditions
    assert (await saved_player(caster))["focus"]["current"] == before["focus"]["current"] - (5 if spell == SLOW else 2)


async def test_cube_targets_ally_and_excludes_structure_and_immune_creature(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, FIRE)
    ally = await add_player(ctx, "warrior")
    immune = await set_foe(ctx, foe_id="immune")
    immune.condition_immunities = {"outlined": "innate immunity"}
    state = ctx.userdata.combat_state
    add_wall(state, "structure", "Wall", pos(32, 8), pos(34, 8))
    positions = spatial_record(state)["positions"]
    for target in ("foe", ally, "immune"):
        positions[target]["x"] = 30
    packets, state = await play(ctx, cast_spell(caster, FIRE))
    cast_packet = receipt(packets, caster)
    assert cast_packet["condition_targets"] == ["foe", ally]
    assert {r["target_id"] for r in cast_packet["condition_results"]} == {"foe", ally, "immune"}
    immunity = next(r for r in cast_packet["condition_results"] if r["target_id"] == "immune")
    assert immunity["condition_immune"] == "outlined" and not immunity["save"]["success"]
    assert participant(state, ally).conditions[0]["source"] == FIRE
    assert not participant(state, "immune").conditions and not participant(state, "structure").conditions


async def test_absorb_magic_only_consumes_its_slow_delivery(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    render = await set_foe(ctx, "hollow_veilrender", hp=100)
    render.hp_current = 70
    await set_foe(ctx, foe_id="other")
    spatial_record(ctx.userdata.combat_state)["positions"]["foe"]["x"] = 60
    before = await saved_player(caster)
    await combat_turn.declare_phase(ctx, [slow(caster, "foe", "other")])
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        resolved = json.loads(await combat_turn.resolve_phase(ctx))
    cast_packet = receipt(resolved["packets"], caster)
    assert cast_packet["absorbed"] == [{"effect": "Absorb Magic", "target_id": "foe", "healed": 15, "hp_current": 85}]
    assert cast_packet["condition_targets"] == ["other"]
    state = await reload(ctx)
    assert participant(state, "foe").hp_current == 85 and not participant(state, "foe").conditions
    assert participant(state, "other").conditions == [instance("slowed", SLOW, caster, "wis")]
    assert (await saved_player(caster))["focus"]["current"] == before["focus"]["current"] - 5


async def test_choir_redirects_one_recipient_without_moving_cube(started):
    ctx, _ = await started("hollow_choir", player_class="druid")
    await search(ctx)
    caster = ctx.userdata.player_id
    await character_spells.record_learned(caster, FIRE, "discovery")
    await set_foe(ctx, foe_id="in_cube")
    await set_foe(ctx, foe_id="near_caster")
    positions = spatial_record(ctx.userdata.combat_state)["positions"]
    positions.update(choir_zone=pos(30), in_cube=pos(32), near_caster=pos(2))
    packets, state = await play(ctx, cast_spell(caster, FIRE, "choir_zone"), face=1)
    results = receipt(packets, caster)["condition_targets"]
    assert results == [caster, "in_cube"]
    assert participant(state, caster).conditions[0]["source"] == FIRE
    for target in ("choir_zone", "near_caster"):
        assert not any(c["type"] == "outlined" for c in participant(state, target).conditions)


async def test_architect_intercepts_only_one_cube_delivery_in_round(archers):
    first, second, _ = archers.players
    for actor in (first, second):
        await archers.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{class}','\"druid\"') WHERE player_id=$1", actor
        )
        await character_spells.record_learned(actor, FIRE, "discovery")
    state = await archers.reload()
    owner = state.architect_encounter["owner_id"]
    for _ in range(3):
        combat_recharge.spend(participant(state, owner), combat_recharge.LEGENDARY_RESISTANCE, state.round_number)
    state.participants.append(_enemy("in_cube", 100))
    state.initiative_order.append("in_cube")
    spatial_record(state)["positions"].update(in_cube=pos(-20, 25), **{second: pos(-25, 40)})
    spatial_record(state)["speeds"]["in_cube"] = 30
    before = await archers.persist()
    await declare(archers, cast(first, FIRE, owner), cast(second, FIRE, owner))
    with forced_rolls(1):
        result = await archers.command("resolve_phase", {})
    first_cast, second_cast = (receipt(result["packets"], actor) for actor in (first, second))
    assert first_cast["condition_targets"] == ["in_cube"]
    assert second_cast["condition_targets"] == [owner]
    assert second_cast["condition_results"][1]["condition_outcome"] == "already_held"
    state = await archers.reload()
    wall = wall_raised(before, state, first)
    assert not wall.conditions
    assert participant(state, owner).conditions[0]["originating_participant_id"] == second


@pytest.mark.parametrize("spell", [FIRE, SLOW])
async def test_condition_cast_skips_a_target_dropped_by_an_earlier_attack(spell_fight, spell):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await prepare_spell(ctx, spell)
    fighter = await add_player(ctx, "warrior")
    await set_foe(ctx, hp=1)
    await set_foe(ctx, foe_id="other")
    await equip(ctx, fighter, CROSSBOW)
    state = ctx.userdata.combat_state
    participant(state, fighter).initiative = 30
    spatial_record(state)["positions"].update(foe=pos(25), other=pos(50), **{fighter: pos(11)})
    action = cast_spell(caster, FIRE) if spell == FIRE else slow(caster, "foe", "other")
    packets, saved = await play(ctx, attack(fighter, CROSSBOW["name"], "foe"), action, faces=[18, 1, 1, 1, 1, 1])
    assert next(p for p in packets if p["actor_id"] == fighter)["target_fallen"]
    resolved = receipt(packets, caster)
    if spell == FIRE:
        assert resolved["condition_results"] == resolved["condition_targets"] == []
    else:
        assert resolved["condition_results"][0]["condition_outcome"] == "ineligible_target"
        assert resolved["condition_targets"] == ["other"]
    assert not participant(saved, "foe").conditions


async def test_slow_refuses_devastating_strike_with_an_automatic_extra_attack(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    warrior = await add_player(ctx, "warrior")
    await set_foe(ctx)
    await equip(ctx, warrior, DAGGER)
    actor = participant(ctx.userdata.combat_state, warrior)
    actor.enhancers = ["extra_attack"]
    actor.level = 10
    strike = AbilityDecl(
        kind="ability",
        actor_id=warrior,
        action="warrior_devastating_strike",
        targets=["foe"],
        argument_type="",
    )
    await play(ctx, slow(caster, warrior))
    before = await saved_player(warrior)
    state = (await reload(ctx)).to_dict()
    with pytest.raises(ToolError, match="Slow"):
        await combat_turn.declare_phase(ctx, [strike])
    assert (await reload(ctx)).to_dict() == state
    assert await saved_player(warrior) == before
    _, saved = await play(ctx, defend(warrior))
    assert participant(saved, warrior).conditions == [instance("slowed", SLOW, caster, "wis")]

    single = strike.model_copy(update={"argument_type": "plain"})
    packets, saved = await play(ctx, single, faces=[18, 1])
    swing = next(p for p in packets if p["actor_id"] == warrior)
    assert swing["hit"] and swing["damage"] > 0 and "attacks" not in swing
    assert participant(saved, "foe").hp_current == 100 - swing["damage"]
    assert (await saved_player(warrior))["stamina"]["current"] == before["stamina"]["current"] - 3
