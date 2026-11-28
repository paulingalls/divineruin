"""Movement settlement and continuation checks through registered tools."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import (
    declare_attacks,
    defense_fight,
    reaction_packet,
    reload_session,
    spend,
)
from acceptance.disruption_reactions_harness import attack_damage, dice, open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_architect_terrain import set_favor
from acceptance.test_bark_skin import keep_original
from acceptance.test_departed_member_leaves_fight import depart_guest
from acceptance.test_guardian_intercept import tool_receipt
from acceptance.test_opportunity_strike import STRIKE, participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_natures_grasp import GRASP
from acceptance.test_spell_reaction_offers import resources
from acceptance.test_still_anchors import strike

from combat_spatial import require_spatial
from conditions import apply_condition
from db_mutations_resonance import update_player_resonance


@pytest.mark.parametrize("cast_grasp", [False, True], ids=["decline", "resist"])
async def test_grasp_and_strike_answer_distinct_windows(reset_db_pool, cast_grasp):
    async with defense_fight("druid", ally_archetype="warrior", library=((0, GRASP),)) as fight:
        target, warrior = fight.players
        mover = fight.enemies[0]
        state = await fight.reload()
        require_spatial(state)["positions"].update({mover: pos(5), warrior: pos(5, 3), target: pos(25)})
        await fight.persist()
        before_hp = participant(state, mover).hp_current
        await declare_attacks(fight, target, mover)
        with dice(18, 18, 18, 18), attack_damage(4, 4):
            start = await open_stage(fight, "movement")
            assert {r["id"] for r in start["reactions"]} == {GRASP}
            if cast_grasp:
                await fight.command("activate", {"id": GRASP})
            result = await fight.command("resolve_phase", {})
            exit_window = result["next"]["waiting_on"]
            assert exit_window["window_id"] != start["window_id"]
            assert {r["id"] for r in exit_window["reactions"]} == {STRIKE}
            if cast_grasp:
                assert reaction_packet(result["packets"], GRASP)["save"]["success"]
            await reload_session(fight)
            receipt = await tool_receipt(fight, warrior, "activate", {"id": STRIKE})
            assert not receipt.is_error, receipt.output
            packets = await fight.drain()
        (hit,) = [p for p in packets if p.get("reaction") == STRIKE]
        state = await fight.reload()
        assert hit["window_id"] == exit_window["window_id"] and hit["hit"] and hit["damage"] > 0
        assert participant(state, mover).hp_current == before_hp - hit["damage"]
        assert require_spatial(state)["positions"][mover] == pos(20)
        assert all(p.get("ability_id") != GRASP for p in packets)


@pytest.mark.parametrize("outcome", ["keep", "departure"])
async def test_fate_save_continuation(reset_db_pool, outcome):
    async with defense_fight("druid", ally_archetype="druid", library=((1, GRASP),)) as fight:
        host, caster = fight.players
        mover = fight.enemies[0]
        await set_favor(fight, "zhael", 40)
        state = await fight.reload()
        require_spatial(state)["positions"].update({mover: pos(35), host: pos(5), caster: pos(0, 5)})
        await fight.persist()
        await reload_session(fight)
        focus, _ = await resources(fight, caster)
        await declare_attacks(fight, host, mover)
        with dice(4):
            await spend(fight, GRASP, stage="movement", actor=caster, cost=2)
            pending = await fight.command("resolve_phase", {})
        assert pending["fate_offer"]["roll_kind"] == "save"
        assert all(p.get("ability_id") != GRASP for p in pending["packets"])
        held = await fight.reload()
        assert require_spatial(held)["positions"][mover] == pos(35)
        assert all(c.get("source") != GRASP for c in participant(held, mover).conditions)
        if outcome == "departure":
            await depart_guest(fight, caster)
        else:
            await reload_session(fight)
        with dice(18, 18, 18, 18):
            result = await fight.command("resolve_phase", {})
            if outcome == "keep":
                assert result["fate_offer"]["roll_kind"] == "save"
                assert not result["packets"]
                assert require_spatial(await fight.reload())["positions"][mover] == pos(35)
                result = await keep_original(fight, result["fate_offer"])
            packets = result["packets"]
            if (await fight.reload()).beat != "declaration":
                if result.get("fate_offer"):
                    packets += (await keep_original(fight, result["fate_offer"]))["packets"]
                if (await fight.reload()).beat != "declaration":
                    packets += await fight.drain()
        state = await fight.reload()
        if outcome == "keep":
            receipt = reaction_packet(packets, GRASP)
            assert receipt["save"]["roll"] == 4 and receipt["condition_inflicted"] == "restrained"
        else:
            assert all(p.get("ability_id") != GRASP for p in packets)
        assert require_spatial(state)["positions"][mover] == pos(35 if outcome == "keep" else 10)
        row = await fight.pool.fetchval(
            "SELECT (data->'focus'->>'current')::int FROM players WHERE player_id=$1", caster
        )
        assert row == focus - 2


@pytest.mark.parametrize("mover", ["bandit", "hollow_architect"], ids=["bonus-die", "legendary-resistance"])
async def test_shared_save_survives_grasp(reset_db_pool, mover):
    async with defense_fight("druid", mover, ally_archetype="druid", library=((0, GRASP),)) as fight:
        caster, target = fight.players
        state = await fight.reload()
        bandit = mover == "bandit"
        require_spatial(state)["positions"].update({target: pos(5), mover: pos(35)})
        reactor = participant(state, caster)
        reactor.attributes["wisdom"] = 18
        enemy = participant(state, mover)
        if bandit:
            await update_player_resonance(caster, 12, conn=fight.pool)
            fight.sd.member_state(caster).resonance.current = 12
            enemy.attributes["strength"] = 10
            enemy.saving_throw_proficiencies = []
            enemy.conditions = apply_condition(enemy.conditions, "blessed", source=target)
        await fight.persist()
        action = "Short Sword" if bandit else "Construct Slam"
        await fight.command("declare_phase", {"declarations": [{"actor_id": mover, **strike(target, action=action)}]})
        with dice(15 if bandit else 2, 3, 3), patch("condition_bonus.dice_roll", return_value=_damage_die(2)):
            await spend(fight, GRASP, stage="movement", cost=2)
            packet = reaction_packet(await fight.drain(), GRASP)
        save = packet["save"]
        assert save["dc"] == 8 + 3 + 4 + (2 if bandit else 0)
        assert save["success"] and "condition_inflicted" not in packet
        await reload_session(fight)
        state = await fight.reload()
        assert require_spatial(state)["positions"][mover] == pos(10 if bandit else 20)
        enemy = participant(state, mover)
        if bandit:
            assert (save["roll"], save["total"]) == (15, 17)
            assert any(c["type"] == "blessed" for c in enemy.conditions)
        else:
            assert save["success_override"] == "Legendary Resistance"
            assert enemy.action_ledger["legendary resistance"]["remaining"] == 2
