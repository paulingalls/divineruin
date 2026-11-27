"""Registered combat tools offer and settle spells from the persisted library."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import (
    action_packet,
    declare_attacks,
    defense_fight,
    hp,
    player_row,
    reaction_packet,
    reload_session,
)
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import strike

import db_mutations_resonance
import spells
from check_resolution import D20Roll

SHIELD = "arcane_shield_spell"
BARK_SKIN = "primal_bark_skin"


async def resources(fight, actor):
    row = await player_row(actor)
    resonance = (await db_mutations_resonance.read_player_resonance(actor))["current"]
    assert fight.sd.member_state(actor).resonance.current == resonance
    return row["focus"]["current"], resonance


async def offered_id(fight, actor, stage, spell_id):
    window = await open_stage(fight, stage)
    (offered,) = [r["id"] for r in window["reactions"] if r["actor_id"] == actor and r["id"] == spell_id]
    return window, offered


@pytest.mark.parametrize("use_reaction", [False, True])
async def test_library_shield_changes_threshold_hit_and_expires(reset_db_pool, use_reaction):
    async with defense_fight("guardian", ally_archetype="artificer", library=((1, SHIELD),)) as fight:
        host, caster = fight.players
        state = await fight.reload()
        target = participant(state, caster)
        target.ac = 16
        await fight.persist()
        await db_mutations_resonance.update_player_resonance(caster, 2, conn=fight.pool)
        await reload_session(fight)
        before = await resources(fight, caster)
        host_before = await resources(fight, host)
        await declare_attacks(fight, caster)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 - self.modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            if use_reaction:
                window, offered = await offered_id(fight, caster, "pre_roll", SHIELD)
                await reload_session(fight)
                receipt = await tool_receipt(fight, caster, "activate", {"id": offered})
                assert not receipt.is_error, receipt.output
                assert json.loads(receipt.output)["resonance_generated"] == 1
                assert await resources(fight, caster) == (before[0] - 1, before[1] + 1)
                state = await fight.reload()
                spend = state.reactions_available[caster]
                assert (spend["ability_id"], spend["window_id"], spend["held_seq"]) == (
                    offered,
                    window["window_id"],
                    state.held_actions[0]["seq"],
                )
                repeat = await tool_receipt(fight, caster, "activate", {"id": offered})
                assert repeat.is_error and "already spent" in repeat.output
                assert await resources(fight, caster) == (before[0] - 1, before[1] + 1)

            packets = await fight.drain()
            for enemy in fight.enemies:
                attack = action_packet(packets, enemy, SWORD)
                assert (attack["target_ac"], attack["hit"], attack["damage"]) == (
                    (19, False, 0) if use_reaction else (16, True, 8)
                )
            assert await hp(fight) == ([100, 100] if use_reaction else [100, 84])
            if use_reaction:
                packet = reaction_packet(packets, SHIELD)
                spell = spells.get_spell(SHIELD)
                assert (packet["ability_name"], packet["narration_cue"]) == (spell.name, spell.narration_cue)
                assert (packet["mechanical_effect"], packet["ac_bonus"]) == ("target_ac_bonus", 3)
                state = await fight.reload()
                assert participant(state, caster).shield_spell_active
                assert await resources(fight, caster) == (before[0] - 1, before[1])
                assert await resources(fight, host) == host_before
                enemy = fight.enemies[0]
                state.initiative_order = [caster, enemy, host, fight.enemies[1]]
                participant(state, caster).initiative = 40
                await fight.persist()
                await fight.command(
                    "declare_phase",
                    {
                        "declarations": [
                            {"actor_id": caster, **strike(fight.enemies[1], action="Longsword")},
                            {"actor_id": enemy, **strike(caster, action=SWORD)},
                        ]
                    },
                )
                packets = await fight.drain()
                attack = action_packet(packets, enemy, SWORD)
                assert (attack["target_ac"], attack["hit"]) == (16, True)
                assert not participant(await fight.reload(), caster).shield_spell_active


@pytest.mark.parametrize("critical", [False, True])
async def test_library_bark_skin_rechecks_roll_and_expires(reset_db_pool, critical):
    async with defense_fight("beastcaller", library=((0, BARK_SKIN),)) as fight:
        caster = fight.players[0]
        enemy, followup = fight.enemies
        state = await fight.reload()
        state.terrain = "forest"
        if critical:
            sword = next(action for action in participant(state, enemy).action_pool if action["name"] == SWORD)
            sword["to_hit"] = -4
        await fight.persist()
        await db_mutations_resonance.update_player_resonance(caster, 2, conn=fight.pool)
        await reload_session(fight)
        before = await resources(fight, caster)
        await declare_attacks(fight, caster)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 - self.modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            window, offered = await offered_id(fight, caster, "post_roll", BARK_SKIN)
            state = await fight.reload()
            head = state.held_actions[0]
            original = head["roll"]["attack_result"]
            assert original["hit"] and original["attack_total"] == head["roll"]["effective_ac"] == 16
            assert (original["roll"] == 20) is critical
            receipt = await tool_receipt(fight, caster, "activate", {"id": offered})
            assert not receipt.is_error, receipt.output
            assert json.loads(receipt.output)["resonance_generated"] == 1
            assert await resources(fight, caster) == (before[0] - 2, before[1] + 1)
            state = await fight.reload()
            spend = state.reactions_available[caster]
            assert (spend["ability_id"], spend["window_id"], spend["held_seq"]) == (
                offered,
                window["window_id"],
                head["seq"],
            )
            packets = await fight.drain()
            attack = action_packet(packets, enemy, SWORD)
            assert (attack["roll"], attack["attack_total"], attack["target_ac"]) == (original["roll"], 16, 18)
            assert attack["hit"] is attack["critical"] is critical
            assert attack["damage"] == (original["damage"] if critical else 0)
            assert await hp(fight) == [100 - attack["damage"], 100]
            packet = reaction_packet(packets, BARK_SKIN)
            assert packet["mechanical_effect"] == "round_ac_bonus"
            attack = action_packet(packets, followup, SWORD)
            assert (attack["target_ac"], attack["hit"]) == (18, False)
            assert not participant(await fight.reload(), caster).bark_skin_active
            assert await resources(fight, caster) == (before[0] - 2, before[1])
            await declare_attacks(fight, caster, followup)
            attack = action_packet(await fight.drain(), followup, SWORD)
            assert (attack["target_ac"], attack["hit"], attack["damage"]) == (16, True, 8)


@pytest.mark.parametrize(
    ("archetype", "spell_id", "twin", "stage", "cost"),
    [
        ("mage", SHIELD, "mage_shield_spell", "pre_roll", 1),
        ("druid", BARK_SKIN, "druid_bark_skin", "post_roll", 2),
        ("warden", BARK_SKIN, "warden_bark_skin", "post_roll", 2),
    ],
)
async def test_archetype_twin_is_the_only_offer(reset_db_pool, archetype, spell_id, twin, stage, cost):
    async with defense_fight(archetype, library=((0, spell_id),)) as fight:
        caster = fight.players[0]
        before = await resources(fight, caster)
        await declare_attacks(fight, caster, fight.enemies[0])
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 - self.modifier)):
            window, offered = await offered_id(fight, caster, stage, twin)
            assert [r["id"] for r in window["reactions"] if r["actor_id"] == caster] == [twin]
            blocked = await tool_receipt(fight, caster, "activate", {"id": spell_id})
            assert blocked.is_error and "does not own reaction" in blocked.output
            assert await resources(fight, caster) == before
            await fight.command("activate", {"id": offered})
            await fight.reload()
            error = await fight.command("activate", {"id": offered}, error=True)
            assert "already spent" in error
            assert await resources(fight, caster) == (before[0] - cost, before[1])
            assert reaction_packet(await fight.drain(), twin)["mechanical_effect"] == (
                "target_ac_bonus" if stage == "pre_roll" else "round_ac_bonus"
            )
            await fight.reload()
            assert await resources(fight, caster) == (before[0] - cost, before[1])


@pytest.mark.parametrize("exit_kind", ["depart", "end_combat"])
async def test_spent_catalog_shield_follows_combat_lifecycle(reset_db_pool, exit_kind):
    async with defense_fight("guardian", ally_archetype="artificer", library=((1, SHIELD),)) as fight:
        caster = fight.players[1]
        state = await fight.reload()
        participant(state, caster).ac = 16
        await fight.persist()
        enemy = fight.enemies[0]
        host = fight.players[0]
        declarations = [{"actor_id": enemy, **strike(caster, action=SWORD)}]
        if exit_kind == "depart":
            declarations.append({"actor_id": fight.enemies[1], **strike(host, action=SWORD)})
        await fight.command("declare_phase", {"declarations": declarations})
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 - self.modifier)):
            _, offered = await offered_id(fight, caster, "pre_roll", SHIELD)
            receipt = await tool_receipt(fight, caster, "activate", {"id": offered})
            assert not receipt.is_error, receipt.output
            before = await player_row(caster)
            packets = []
            if exit_kind == "depart":
                held = await fight.command("resolve_phase", {})
                assert held["next"]["waiting_on"]["target_id"] == host
                packets.extend(held["packets"])
                assert participant(await fight.reload(), caster).shield_spell_active
                fight.sd.party.members = [member for member in fight.sd.party.members if member.player_id != caster]
            packets.extend(await fight.drain())
        reaction_packet(packets, SHIELD)
        assert action_packet(packets, enemy, SWORD)["target_ac"] == 19
        state = await fight.reload()
        assert participant(state, caster).shield_spell_active
        assert not state.reactions_available.get(caster, {}).get("spent")
        assert (await player_row(caster))["focus"] == before["focus"]
        if exit_kind == "depart":
            assert (await player_row(caster))["resonance"] == before["resonance"]
        else:
            await fight.command("end_combat", {"outcome": "fled"})
            await fight.command("enter_mode", {"mode": "combat", "encounter_id": fight.encounter_id})
            state = await fight.reload()
            assert SHIELD in participant(state, caster).reaction_ids
            assert not participant(state, caster).shield_spell_active
            assert not state.reactions_available.get(caster, {}).get("spent")
