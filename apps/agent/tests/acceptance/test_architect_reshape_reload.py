from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import (
    WORKS,
    enter,
    fresh_session,
    pos,
    reopen,
)
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_terrain import declare, play, set_favor

import combat_spatial
import db_queries
from db_mutations_concentration import update_player_concentration


def terrain(state):
    return state.architect_encounter, state.spatial["structures"], state.spatial["movement_areas"]


@pytest.mark.parametrize("reload_offer", [True, False])
async def test_floor_and_ceiling_resume_once_through_fate_and_reaction(fight, reload_offer):
    state = await fight.reload()
    player = fight.players[0]
    owner = state.architect_encounter["owner_id"]
    target = state.get_participant(player)
    target.reaction_ids = ["cleric_shield_of_faith"]
    target.has_reaction_ability = True
    target.attributes["dexterity"] = 10
    state.get_participant(owner).hp_current = 149
    combat_spatial.place(state, player, pos(5))
    await fight.persist()
    await set_favor(fight, "zhael", 40)
    floor = {"kind": "open_floor", "min": pos(4, -5), "max": pos(6, 5)}
    ceiling = {"kind": "lower_ceiling", "min": pos(23, -5), "max": pos(29, 5)}
    await declare(
        fight, defend(player), {**attack(owner, player), "action": "Geometry Strike", "reshape": [floor, ceiling]}
    )
    await fight.command("resolve_phase", {})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)) as d20,
        patch("architect_reshape.dice.roll", return_value=_damage_die(8)) as damage,
    ):
        paused = await fight.command("resolve_phase", {})
        assert paused["architect"]["reshape_uses_remaining"] == 1
        offer = paused["fate_offer"]
        assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (player, "save", 1)
        saved = await fight.reload()
        saved_terrain = terrain(saved)
        record = saved.architect_encounter
        assert record["reshape_count"] == 1 and record["reshape_round"] == saved.round_number
        assert len(record["floors"]) == 1 and record["pits"] == {}
        assert len(saved.spatial["movement_areas"]) == 1
        assert saved.get_participant(player).hp_current == 100

        if reload_offer:
            await fresh_session(fight, saved)
            assert terrain(await fight.reload()) == saved_terrain
            window = await fight.command("resolve_phase", {})
        else:
            window = await fight.command(
                "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
            )
        await set_favor(fight, "mortaen", 0)
        assert window["next"]["waiting_on"]["stage"] == "pre_roll"
        assert window["architect"]["reshape_uses_remaining"] == 0

        saved = await fight.reload()
        saved_terrain = terrain(saved)
        assert saved.architect_encounter["reshape_count"] == 2
        assert len(saved.spatial["movement_areas"]) == 2
        assert saved.architect_encounter["pits"] == {player: next(iter(record["floors"]))}
        assert saved.get_participant(player).hp_current == 92 and d20.call_count == 1

        await fresh_session(fight, saved)
        assert terrain(await fight.reload()) == saved_terrain
        summaries = await fight.drain()
    damage.assert_called_once_with("2d6")
    assert d20.call_count == 3  # Save, then the disadvantaged ranged attack against a prone target.
    [summary] = [item for item in summaries if item["actor_id"] == owner]
    assert not summary["hit"]
    assert [receipt["kind"] for receipt in summary["reshape"]] == ["open_floor", "lower_ceiling"]
    [target_result] = summary["reshape"][0]["results"]
    assert (target_result["target_id"], target_result["damage"], target_result["prone"]) == (player, 8, True)
    assert terrain(await fight.reload()) == saved_terrain
    row = await db_queries.get_player(player)
    assert row is not None and row["hp"]["current"] == 92


async def test_changed_walls_and_terrain_survive_flee_reentry(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    state.get_participant(owner).hp_current = 149
    await fight.persist()
    floor = {"kind": "open_floor", "min": pos(36), "max": pos(45, 5)}
    ceiling = {"kind": "lower_ceiling", "min": pos(36), "max": pos(45, 5)}
    wall = {"kind": "create_wall", "start": pos(35), "end": pos(35, 5)}
    await play(fight, owner, {**defend(owner), "reshape": [floor]})
    await play(fight, owner, {**defend(owner), "reshape": [wall, ceiling]})
    before = await fight.reload()
    assert len(before.architect_encounter["structure_ids"]) == 3
    assert len(before.architect_encounter["floors"]) == 1
    assert len(before.spatial["movement_areas"]) == 2
    assert before.architect_encounter["reshape_count"] == 2
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    after = await enter(fight)
    assert terrain(after) == terrain(before)
    assert after.round_number == before.round_number


async def test_floor_captures_multiple_creatures_and_resolves_each_save(reset_db_pool):
    fight = MawlingHarness()
    try:
        await fight.prepare((20, 20), companion=None, location=WORKS)
        state = await enter(fight)
        assert state.architect_encounter is not None
        owner = state.architect_encounter["owner_id"]
        failed, saved = fight.players
        combat_spatial.place(state, failed, pos(6))
        combat_spatial.place(state, saved, pos(7))
        combat_spatial.place(state, owner, pos(5, 0, 5))
        for actor_id in fight.players:
            actor = state.get_participant(actor_id)
            assert actor is not None
            actor.attributes["dexterity"] = 10
        await fight.persist()
        await set_favor(fight, "zhael", 40)
        await update_player_concentration(failed, "divine_bless")
        fight.sd.concentration.spell_id = "divine_bless"
        floor = {"kind": "open_floor", "min": pos(5, -5), "max": pos(7, 5)}
        await declare(fight, {**defend(owner), "reshape": [floor]})
        await fight.command("resolve_phase", {})

        async def keep(result):
            return await fight.command(
                "activate",
                {"id": "zhael_fates_thread", "offer_id": result["fate_offer"]["offer_id"], "keep": "original"},
            )

        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20), _d20(20)]) as rolls,
            patch("architect_reshape.dice.roll", return_value=_damage_die(8)) as damage,
        ):
            first_save = await fight.command("resolve_phase", {})
            assert first_save["fate_offer"]["roller_id"] == failed
            concentration = await keep(first_save)
            assert concentration["fate_offer"]["roller_id"] == failed
            state = await fight.reload()
            first = state.get_participant(failed)
            assert first is not None and first.hp_current == 92
            second_save = await keep(concentration)
            assert second_save["fate_offer"]["roller_id"] == saved
            state = await fight.reload()
            [first_result] = state.held_actions[0]["reshape_receipts"][0]["results"]
            assert first_result["target_id"] == failed
            resolved = await keep(second_save)
        [summary] = [packet for packet in resolved["packets"] if packet["actor_id"] == owner]
        [receipt] = summary["reshape"]
        assert receipt["targets"] == [failed, saved]
        assert [result["save_success"] for result in receipt["results"]] == [False, True]
        assert rolls.call_count == 3
        damage.assert_called_once_with("2d6")
        reloaded = await fight.reload()
        assert reloaded.architect_encounter is not None
        assert reloaded.architect_encounter["pits"] == {failed: receipt["section_id"]}
        untouched = reloaded.get_participant(saved)
        assert untouched is not None and untouched.hp_current == 100 and not untouched.conditions
    finally:
        await fight.close()
