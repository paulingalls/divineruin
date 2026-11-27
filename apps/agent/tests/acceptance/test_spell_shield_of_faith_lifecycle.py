"""Saved wards across turn boundaries, departure and held damage settlement."""

from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance._enemy_opportunity_helpers import move, strikes
from acceptance.counter_reactions_harness import RIPOSTE, WEAPON
from acceptance.defensive_reactions_harness import SPELL, declare_attacks, defense_fight, player_row, reaction_packet
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import blow, keep_original
from acceptance.test_guardian_intercept import BANDIT, SWORD
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_spell_shield_of_faith import FAITH, WARD, open_hit, set_target, spend_faith, ward_sources
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

import conditions
from check_resolution import D20Roll
from combat_spatial import require_spatial


@pytest.mark.parametrize("caster_turn", ["omitted", "stunned", "fallen", "absent", "target_left"])
async def test_caster_turn_expires_ward_even_without_an_action(reset_db_pool, caster_turn):
    async with defense_fight(
        "warden", ally_archetype="diplomat", extra_archetypes=("warrior",), library=((1, FAITH),)
    ) as fight:
        ally, caster, guest = fight.players
        modifier = await set_target(fight, ally, caster=caster)
        await declare_attacks(fight, ally, BANDIT)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(17 - modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            await spend_faith(fight, caster, await open_stage(fight, "post_roll"))
            assert blow(await fight.drain())["target_ac"] == 18
            state = await fight.reload()
            assert ward_sources(state, ally) == [caster]
            target = participant(state, ally)
            target.initiative = 25
            participant(state, caster).initiative = 10
            require_spatial(state)["positions"].update({BANDIT: pos(0), ally: pos(3), "lookout": pos(25, 5)})
            source = participant(state, caster)
            if caster_turn == "stunned":
                source.conditions = conditions.apply_condition(source.conditions, "stunned", duration=1)
            if caster_turn == "fallen":
                source.hp_current = 0
                source.is_fallen = True
            await fight.persist()
            declarations = [
                move(ally, 20),
                {"actor_id": "lookout", **strike(ally, action=SWORD)},
            ]
            if caster_turn == "target_left":
                declarations.append(
                    {
                        "actor_id": caster,
                        "kind": "ability",
                        "action": "diplomat_inspire",
                        "targets": [guest],
                        "argument_type": "",
                    }
                )
            await fight.command("declare_phase", {"declarations": declarations})
            lifecycle = _live_party(fight.sd, *fight.players)
            try:
                if caster_turn != "absent":
                    await lifecycle.authorize(caster)
                if caster_turn == "target_left":
                    await lifecycle.authorize(guest)
                    await leave(fight.sd, guest, room_io=MagicMock())
                packets = await fight.drain()
            finally:
                await lifecycle.aclose()
        (opportunity,) = strikes(packets)
        assert (opportunity["target_ac"], opportunity["hit"], opportunity["damage"]) == (18, False, 0)
        attack = blow(packets, "lookout")
        assert (attack["target_ac"], attack["hit"], attack["damage"]) == (16, True, 7)
        assert ward_sources(await fight.reload(), ally) == []
        if caster_turn == "target_left":
            assert any(p["actor_id"] == caster and p.get("outcome") == "target_left" for p in packets)


@pytest.mark.parametrize("exit_kind", ["recipient_leaves", "caster_leaves_before_close", "caster_leaves", "end_combat"])
async def test_faith_drops_on_departure_or_combat_end(reset_db_pool, exit_kind):
    async with defense_fight(
        "warden", ally_archetype="diplomat", extra_archetypes=("warrior",), library=((1, FAITH),)
    ) as fight:
        ally, caster, guest = fight.players
        target = guest if exit_kind == "recipient_leaves" else ally
        modifier = await set_target(fight, target, caster=caster)
        await declare_attacks(fight, target, BANDIT)
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(17 - modifier)):
            await spend_faith(fight, caster, await open_stage(fight, "post_roll"))
            settled = (await player_row(caster))["focus"]
            if exit_kind == "end_combat":
                assert blow(await fight.drain())["target_ac"] == 18
                await fight.command("end_combat", {"outcome": "fled"})
                await fight.command("enter_mode", {"mode": "combat", "encounter_id": fight.encounter_id})
            else:
                if exit_kind == "caster_leaves":
                    assert blow(await fight.drain())["target_ac"] == 18
                    assert ward_sources(await fight.reload(), target) == [caster]
                departing = guest if exit_kind == "recipient_leaves" else caster
                lifecycle = _live_party(fight.sd, *fight.players)
                try:
                    await lifecycle.authorize(departing)
                    await leave(fight.sd, departing, room_io=MagicMock())
                    if exit_kind == "caster_leaves_before_close":
                        attack = blow(await fight.drain())
                        assert (attack["target_ac"], attack["hit"]) == (16, True)
                    if exit_kind == "recipient_leaves":
                        packets = await fight.drain()
                        assert any(p.get("target_id") == target and p.get("outcome") == "target_left" for p in packets)
                        assert all(p.get("ability_id") != FAITH for p in packets)
                finally:
                    await lifecycle.aclose()
        state = await fight.reload()
        assert all(c["type"] != WARD for p in state.participants for c in p.conditions)
        assert (await player_row(caster))["focus"] == settled
        assert all(c["type"] != WARD for c in (await player_row(target)).get("conditions", []))


@pytest.mark.parametrize("depart", [False, True])
async def test_applied_faith_survives_held_concentration_save(reset_db_pool, depart):
    async with defense_fight("warden", ally_archetype="diplomat", library=((1, FAITH),), fate=True) as fight:
        ally, caster = fight.players
        modifier = await set_target(fight, ally, caster=caster)
        initial_hp = (await player_row(ally))["hp"]["current"]
        await declare_attacks(fight, ally)
        faces = iter((18 - modifier, 7, 17 - modifier))
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(next(faces))),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window, original = await open_hit(fight, True, (18 - modifier, 18, 16))
            await spend_faith(fight, caster, window)
            paused = await fight.command("resolve_phase", {})
            offer = paused["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", ally)
            head = (await fight.reload()).held_actions[0]
            assert head["roll"]["effective_ac"] == 18
            assert reaction_packet(head["pending_reaction_packets"], FAITH)["target_id"] == ally
            assert (await player_row(ally))["hp"]["current"] == initial_hp - original["damage"]
            lifecycle = _live_party(fight.sd, *fight.players)
            try:
                if depart:
                    await lifecycle.authorize(caster)
                    await leave(fight.sd, caster, room_io=MagicMock())
                    assert ward_sources(await fight.reload(), ally) == []
                result = await keep_original(fight, offer)
                packets = result["packets"]
                for _ in range(6):
                    if (await fight.reload()).round_number == 2:
                        break
                    if next_offer := result.get("fate_offer"):
                        result = await keep_original(fight, next_offer)
                    else:
                        result = await fight.command("resolve_phase", {})
                    packets += result["packets"]
                else:
                    raise AssertionError("held and follow-up strikes did not finish")
            finally:
                await lifecycle.aclose()
        first = blow(packets)
        assert (first["target_ac"], first["damage"], first["concentration_broken"]) == (18, original["damage"], SPELL)
        assert reaction_packet(packets, FAITH)["actor_id"] == caster
        followup = blow(packets, "lookout")
        assert (followup["target_ac"], followup["hit"], followup["damage"]) == (
            (16, True, 7) if depart else (18, False, 0)
        )
        assert (await player_row(ally))["hp"]["current"] == initial_hp - original["damage"] - followup["damage"]


async def test_departure_preserves_the_rechecked_miss_but_exposes_the_next_hit(reset_db_pool):
    async with defense_fight("skirmisher", ally_archetype="diplomat", library=((1, FAITH),), gear=WEAPON) as fight:
        ally, caster = fight.players
        modifier = await set_target(fight, ally, caster=caster)
        await declare_attacks(fight, ally)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(17 - modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            await spend_faith(fight, caster, await open_stage(fight, "post_roll"))
            paused = await fight.command("resolve_phase", {})
            window = paused["next"]["waiting_on"]
            assert window["stage"] == "post_reaction_miss" and RIPOSTE in {o["id"] for o in window["reactions"]}
            state = await fight.reload()
            assert ward_sources(state, ally) == [caster] and state.held_actions[0]["roll"]["effective_ac"] == 18
            lifecycle = _live_party(fight.sd, *fight.players)
            try:
                await lifecycle.authorize(caster)
                await leave(fight.sd, caster, room_io=MagicMock())
                assert ward_sources(await fight.reload(), ally) == []
                packets = await fight.drain()
            finally:
                await lifecycle.aclose()
        first = blow(packets)
        assert (first["attack_total"], first["target_ac"], first["hit"], first["damage"]) == (17, 18, False, 0)
        followup = blow(packets, "lookout")
        assert (followup["target_ac"], followup["hit"], followup["damage"]) == (16, True, 7)
        assert reaction_packet(packets, FAITH)["actor_id"] == caster
