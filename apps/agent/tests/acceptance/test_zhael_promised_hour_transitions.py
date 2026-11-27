"""Promised Hour objectives settle through registered combat tools."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._promised_hour_fixtures import manual_save, oath_record, promised_fight, select_oath, wrap
from acceptance.test_valdris_oath_breach import dev_db_pool as dev_db_pool
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import GOBLIN, OTHER, dice, goblin_strike
from voice_condition_fixtures import participant, place_actors

import db
import db_mutations
import db_queries


async def assert_change(f, result, oath, status, reason, round_number):
    record = await oath_record(f)
    assert record["status"] == status
    [change] = result["oath_changes"]
    assert (change["oath_id"], change["new_status"], change["reason"], change["round_number"]) == (
        oath["oath_id"],
        status,
        reason,
        round_number,
    )
    assert record["latest_state_change_event_id"] == change["event_id"] != oath["latest_state_change_event_id"]
    assert (record["round_number"], record["transition_round"]) == (2, round_number)
    return record


async def test_target_defeat_settles_with_attack(world) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        oath = await select_oath(f)
        await f.round(faces=())
        await f.declare(attack(f.hero, GOBLIN))
        with dice(19):
            result = await f.call("resolve_phase")
        record = await assert_change(f, result, oath, "fulfilled", "target_defeated", 3)
        await f.reload()
        save = await manual_save(f)
        assert (save["total"], save["oath_timed"]["modifier"]) == (9, 0)
        assert "oath_changes" not in await wrap(f)
        assert await oath_record(f) == record


async def test_missed_deadline_has_no_penalty(world) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        oath = await select_oath(f)
        before = await db_queries.get_player(f.hero)
        await f.round(faces=())
        await f.declare()
        result = await wrap(f)
        assert result["round"] == 4
        lapsed = await assert_change(f, result, oath, "lapsed", "deadline", 3)
        after = await db_queries.get_player(f.hero)
        assert before is not None and after is not None
        for key in ("divine_favor", "patron_gifts", "oath_session_id"):
            assert before.get(key) == after.get(key)
        save = await manual_save(f)
        assert (save["total"], save["oath_timed"]["modifier"]) == (9, 0)
        await f.declare(attack(f.hero, GOBLIN))
        with dice(19):
            result = await f.call("resolve_phase")
        assert "oath_changes" not in result
        assert await oath_record(f) == lapsed


@pytest.mark.parametrize(
    ("objective", "ending", "status", "reason"),
    [
        ("defeat_target", "standalone", "lapsed", "encounter_ended"),
        ("defeat_target", "finishing_blow", "fulfilled", "target_defeated"),
        ("defeat_target", "other_foe", "lapsed", "encounter_ended"),
        ("keep_ally_standing", "finishing_blow", "fulfilled", "ally_stood"),
        ("keep_ally_standing", "standalone", "lapsed", "encounter_ended"),
    ],
)
async def test_terminal_receipt(world, objective, ending, status, reason) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        oath = await select_oath(f, objective=objective, target=f.ally if objective == "keep_ally_standing" else GOBLIN)
        if ending == "standalone":
            _, result = await f.call("end_combat", outcome="fled")
            await assert_change(f, result, oath, status, reason, 2)
        else:
            await f.round(faces=())
            state = f.session.combat_state
            victim = OTHER if ending == "other_foe" else GOBLIN
            participant(state, OTHER).hp_current = 4
            if ending == "other_foe":
                state.participants.remove(participant(state, GOBLIN))
                state.initiative_order.remove(GOBLIN)
                place_actors(state)
            else:
                lost = participant(state, OTHER)
                lost.hp_current = 0
                lost.is_fallen = True
                state.initiative_order.remove(OTHER)
            await f.declare(attack(f.hero, victim))
            with dice(19):
                attack_result = await f.call("resolve_phase")
            result = await wrap(f)
            if reason == "target_defeated":
                await assert_change(f, attack_result, oath, status, reason, 3)
                assert "oath_changes" not in result
            else:
                await assert_change(f, result, oath, status, reason, 3)
        assert await db_mutations.load_combat_state(f.combat_id) is None


@pytest.mark.parametrize("exclusion", ["past", "patron", "archetype", "encounter", "clause"])
async def test_save_exclusions(world, exclusion) -> None:
    async with promised_fight(world) as f:
        await select_oath(f)
        assert (await manual_save(f))["total"] == 10
        state = f.session.combat_state
        if exclusion == "past":
            state.round_number = 4
        elif exclusion == "patron":
            await configure(world, "thyra", "paladin")
        elif exclusion == "archetype":
            await configure(world, "zhael", "warrior")
        elif exclusion == "encounter":
            state.combat_id += "-different"
        with patch("oath_timed.has_engine_clause", return_value=False) if exclusion == "clause" else nullcontext():
            save = await manual_save(f)
        assert (save["total"], save["oath_timed"]["modifier"]) == (9, 0)


async def test_defeat_rolls_back_on_failed_combat_persist(world) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        oath = await select_oath(f)
        await f.declare(attack(f.hero, GOBLIN))
        original = deepcopy((await f.reload()).to_dict())
        before = await oath_record(f)
        with (
            patch("db_mutations.save_combat_state", side_effect=RuntimeError("persistence failed")),
            dice(19),
            pytest.raises((RuntimeError, ToolError), match="persistence failed"),
        ):
            await f.call("resolve_phase")
        assert await oath_record(f) == before
        assert (await f.reload()).to_dict() == original
        with dice(19):
            result = await f.call("resolve_phase")
        await assert_change(f, result, oath, "fulfilled", "target_defeated", 2)


async def test_defeat_leaves_an_oath_from_another_encounter_untouched(world) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        await select_oath(f)
        async with db.transaction() as conn:
            await conn.execute(
                "UPDATE players SET data = jsonb_set(data, '{oaths,records,0,combat_id}', to_jsonb($2::text))"
                " WHERE player_id = $1",
                f.hero,
                "earlier_encounter",
            )
        before = await oath_record(f)
        await f.declare(attack(f.hero, GOBLIN))
        with dice(19):
            await f.call("resolve_phase")
        assert await oath_record(f) == before


async def test_ally_fall_lapses_immediately(world) -> None:
    async with promised_fight(world, ally_hp=9) as f:
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally)
        await f.declare(goblin_strike(GOBLIN, f.ally))
        first = await wrap(f, 19)
        assert "oath_changes" not in first
        assert participant(await f.reload(), f.ally).hp_current == 4
        assert (await oath_record(f))["status"] == "active"
        await f.declare(goblin_strike(GOBLIN, f.ally))
        result = await wrap(f, 19)
        record = await assert_change(f, result, oath, "lapsed", "ally_fell", 3)
        assert participant(await f.reload(), f.ally).hp_current == 0
        assert (await manual_save(f))["total"] == 9
        assert await oath_record(f) == record


async def test_death_ward_prevents_the_zero_hp_fact(world) -> None:
    async with promised_fight(world) as f:
        await configure(world, "mortaen", "warrior", index=1)
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally, deadline=5)
        await f.declare(goblin_strike(GOBLIN, f.ally))
        first = await wrap(f, 19)
        assert any(packet.get("gift_triggered") == "Death Ward" for packet in first["packets"])
        assert participant(await f.reload(), f.ally).hp_current == 1
        assert (await oath_record(f))["status"] == "active"
        assert "oath_changes" not in first
        await f.declare(goblin_strike(GOBLIN, f.ally))
        await assert_change(f, await wrap(f, 19), oath, "lapsed", "ally_fell", 3)


async def test_dawns_embrace_revives_after_lapse(world) -> None:
    async with promised_fight(world) as f:
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally)
        await configure(world, "orenthel", "paladin", divine_favor={"patron": "orenthel", "level": 90, "max": 100})
        await f.declare(goblin_strike(GOBLIN, f.ally))
        result = await wrap(f, 19)
        assert any(p.get("gift_triggered") == "Dawn's Embrace" for p in result["packets"])
        assert participant(await f.reload(), f.ally).hp_current > 0
        await assert_change(f, result, oath, "lapsed", "ally_fell", 2)


async def test_inner_fire_lapse_survives_same_round_revive(world) -> None:
    async with promised_fight(world) as f:
        await configure(world, "thyra", "warrior", index=1, race="draethar", hp={"current": 5, "max": 20})
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally)
        with (
            f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None),
            patch("draethar_inner_fire.dice.roll", return_value=_damage_die(5)),
        ):
            result = await f.call("activate", id="draethar_inner_fire")
        lapsed = await assert_change(f, result, oath, "lapsed", "ally_fell", 2)
        assert result["hp_remaining"] == 0
        with patch("combat_resolution.dice_roll", return_value=_d20(20)):
            save = await f.call("request_death_save", player_id=f.ally)
        assert save["revived"] is True
        assert f.session.combat_state.round_number == 2
        assert participant(await f.reload(), f.ally).hp_current == 1
        assert (await manual_save(f))["total"] == 9
        assert await oath_record(f) == lapsed


async def test_fortitude_is_not_a_defeat(world) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        goblin = participant(f.session.combat_state, GOBLIN)
        goblin.unholy_fortitude = {"save": "CON", "dc": 10, "increment": 5, "narration_cue": "It rises."}
        oath = await select_oath(f)
        await f.declare(attack(f.hero, GOBLIN))
        with dice(19, 16):
            result = await f.call("resolve_phase")
        assert next(p["unholy_fortitude"] for p in result["packets"] if "unholy_fortitude" in p)["success"]
        assert participant(await f.reload(), GOBLIN).hp_current == 1
        assert "oath_changes" not in result
        assert (await oath_record(f))["status"] == "active"
        await wrap(f)
        await f.declare(attack(f.hero, GOBLIN))
        with dice(19, 2):
            result = await f.call("resolve_phase")
        await assert_change(f, result, oath, "fulfilled", "target_defeated", 3)


@pytest.mark.parametrize("terminal", [False, True])
async def test_patron_damage_activation_returns_its_oath_change(world, terminal: bool) -> None:
    async with promised_fight(world, goblin_hp=4) as f:
        oath = await select_oath(f)
        state = f.session.combat_state
        state.terrain = "forest"
        if terminal:
            participant(state, OTHER).hp_current = 4
        await configure(world, "thyra", "warrior", index=1, divine_favor={"patron": "thyra", "level": 90, "max": 100})
        with (
            f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None),
            patch("thyra_wrath.dice.roll", return_value=SimpleNamespace(notation="3d8", total=15)),
        ):
            result = await f.call("activate", id="thyra_wildmothers_wrath")
        if terminal:
            _, result = result
            assert result["outcome"] == "victory"
        else:
            assert participant(await f.reload(), GOBLIN).hp_current == 0
        await assert_change(f, result, oath, "fulfilled", "target_defeated", 2)


async def test_unbound_ally_fall_does_not_lapse_the_oath(world) -> None:
    async with promised_fight(world) as f:
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally)
        participant(f.session.combat_state, f.hero).hp_current = 4
        await f.declare(goblin_strike(GOBLIN, f.hero))
        result = await wrap(f, 19)
        assert participant(await f.reload(), f.hero).hp_current == 0
        assert (await oath_record(f))["status"] == "active"
        assert "oath_changes" not in result
        await f.declare(goblin_strike(GOBLIN, f.ally))
        await assert_change(f, await wrap(f, 19), oath, "lapsed", "ally_fell", 3)
