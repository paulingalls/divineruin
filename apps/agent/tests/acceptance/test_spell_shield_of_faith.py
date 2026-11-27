"""Shield of Faith through registered combat tools and saved combat state."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import (
    declare_attacks,
    defense_fight,
    player_row,
    reaction_packet,
    reload_session,
)
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import blow, keep_original
from acceptance.test_guardian_intercept import BANDIT, SWORD, pools, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_reaction_offers import resources

import combat_spatial
from check_resolution import D20Roll

FAITH = "divine_shield_of_faith"
WARD = "shield_of_faith"


BARK = "warden_bark_skin"


async def set_target(fight, ally, *, distance=25, ac=16, caster=None):
    state = await fight.reload()
    participant(state, ally).ac = ac
    positions = combat_spatial.require_spatial(state)["positions"]
    positions.update({caster or fight.players[0]: pos(distance), ally: pos(0)})
    sword = next(action for action in participant(state, BANDIT).action_pool if action["name"] == SWORD)
    await fight.persist()
    return sword["to_hit"]


async def spend_faith(fight, caster, window):
    assert (caster, FAITH) in {(offer["actor_id"], offer["id"]) for offer in window["reactions"]}
    before = await resources(fight, caster)
    receipt = await tool_receipt(fight, caster, "activate", {"id": FAITH})
    assert not receipt.is_error, receipt.output
    await reload_session(fight)
    assert await resources(fight, caster) == (before[0] - 2, before[1] + 1)
    state = await fight.reload()
    spend = state.reactions_available[caster]
    assert (spend["ability_id"], spend["window_id"], spend["held_seq"]) == (
        FAITH,
        window["window_id"],
        state.held_actions[0]["seq"],
    )


def ward_sources(state, ally):
    return [c["originating_participant_id"] for c in participant(state, ally).conditions if c["type"] == WARD]


@pytest.mark.parametrize("use_reaction", [True, False])
async def test_catalog_faith_rechecks_ally_hit_and_expires_at_caster_turn(reset_db_pool, use_reaction):
    async with defense_fight("diplomat", ally_archetype="warden", library=((0, FAITH),)) as fight:
        caster, ally = fight.players
        state = await fight.reload()
        assert {reaction for reaction in participant(state, caster).reaction_ids if reaction.endswith(WARD)} == {FAITH}
        target = participant(state, ally)
        target.ac = 16
        target.hp_current = 3
        await fight.pool.execute("UPDATE players SET data=jsonb_set(data,'{hp,current}','3') WHERE player_id=$1", ally)
        combat_spatial.require_spatial(state)["positions"].update({caster: pos(25), ally: pos(0)})
        sword = next(action for action in participant(state, BANDIT).action_pool if action["name"] == SWORD)
        sword["bonus_damage"] = {"dice": "1d6", "damage_type": "necrotic"}
        face = 17 - sword["to_hit"]
        await fight.persist()
        before = await resources(fight, caster)
        await declare_attacks(fight, ally)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(face)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window, original = await open_hit(fight, False, (face, 17, 16))
            assert {"id": FAITH, "actor_id": caster}.items() <= next(
                offer for offer in window["reactions"] if offer["id"] == FAITH
            ).items()
            assert "on_ally_hit" in window["triggers"]
            await reload_session(fight)
            if use_reaction:
                await spend_faith(fight, caster, window)
            packets = await fight.drain()
            attack = blow(packets)
            assert (attack["roll"], attack["attack_total"]) == (original["roll"], original["attack_total"])
            if not use_reaction:
                assert attack["hit"] and attack["damage"] >= 3
                assert participant(await fight.reload(), ally).is_fallen
                return
            for actor in fight.enemies:
                attack = blow(packets, actor)
                assert (attack["target_ac"], attack["hit"], attack["damage"]) == (18, False, 0)
            ward = reaction_packet(packets, FAITH)
            assert (ward["actor_id"], ward["target_id"], ward["ac_bonus"]) == (caster, ally, 2)
            assert (await pools(fight))[1] == (3, 0)
            state = await fight.reload()
            assert not participant(state, ally).is_fallen
            assert ward_sources(state, ally) == [caster]

            await declare_attacks(fight, ally, BANDIT)
            next_attack = blow(await fight.drain())
            assert (next_attack["target_ac"], next_attack["hit"]) == (16, True)
            assert (await player_row(caster))["focus"]["current"] == before[0] - 2


async def test_faith_keeps_natural_twenty_and_spends_focus(reset_db_pool):
    async with defense_fight("diplomat", ally_archetype="warden", library=((0, FAITH),)) as fight:
        caster, ally = fight.players
        modifier = await set_target(fight, ally, ac=24)
        before = await pools(fight)
        await declare_attacks(fight, ally)
        faces = iter((20, 25 - modifier))
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(next(faces))),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window, original = await open_hit(fight, False, (20, 20 + modifier, 24))
            assert original["attack_total"] < 26
            await spend_faith(fight, caster, window)
            packets = await fight.drain()
        attack = blow(packets)
        assert (attack["roll"], attack["target_ac"], attack["hit"], attack["critical"]) == (20, 26, True, True)
        assert attack["damage"] == original["damage"] > 0
        followup = blow(packets, fight.enemies[1])
        assert (followup["target_ac"], followup["hit"], followup["damage"]) == (26, False, 0)
        assert (await pools(fight))[1][0] == before[1][0] - original["damage"]


async def open_hit(fight, fate, expected_roll):
    if fate:
        for _ in range(4):
            result = await fight.command("resolve_phase", {})
            if offer := result.get("fate_offer"):
                break
            if window := result["next"]["waiting_on"]:
                assert window["stage"] == "pre_roll", result
        else:
            raise AssertionError(f"No held hostile attack: {result}")
        head = (await fight.reload()).held_actions[0]
        assert "fate_attack" in head and offer["roller_id"] == BANDIT and offer["die"] == expected_roll[0]
        await reload_session(fight)
        result = await fight.command("resolve_phase", {})
        if reoffered := result.get("fate_offer"):
            assert reoffered["die"] == offer["die"]
            result = await keep_original(fight, reoffered)
        window = result["next"]["waiting_on"]
    else:
        window = await open_stage(fight, "post_roll")
    assert window["stage"] == "post_roll"
    original = (await fight.reload()).held_actions[0]["roll"]["attack_result"]
    assert (original["roll"], original["attack_total"], original["target_ac"]) == expected_roll
    assert original["hit"]
    return window, original


@pytest.mark.parametrize(("fate", "margin"), [(False, 1), (False, 3), (True, 1), (True, 3)])
async def test_bark_and_faith_combine_on_original_roll(reset_db_pool, fate, margin):
    async with defense_fight("diplomat", ally_archetype="warden", library=((0, FAITH),), fate=fate) as fight:
        caster, ally = fight.players
        modifier = await set_target(fight, ally)
        total = 16 + margin
        before = await pools(fight)
        bark_before = await resources(fight, ally)
        await declare_attacks(fight, ally)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(total - modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window, original = await open_hit(fight, fate, (total - modifier, total, 16))
            assert (ally, BARK) in {(offer["actor_id"], offer["id"]) for offer in window["reactions"]}
            receipt = await tool_receipt(fight, ally, "activate", {"id": BARK})
            assert not receipt.is_error, receipt.output
            await reload_session(fight)
            assert await resources(fight, ally) == (bark_before[0] - 2, bark_before[1])
            await spend_faith(fight, caster, window)
            result = await fight.command("resolve_phase", {})
            packets = result["packets"]
            if offer := result.get("fate_offer"):
                packets += (await keep_original(fight, offer))["packets"]
            if (await fight.reload()).round_number == 1:
                packets += await fight.drain()
        attack = blow(packets)
        assert (attack["roll"], attack["attack_total"], attack["target_ac"], attack["hit"], attack["damage"]) == (
            original["roll"],
            total,
            20,
            False,
            0,
        )
        followup = blow(packets, fight.enemies[1])
        assert (followup["target_ac"], followup["hit"], followup["damage"]) == (20, False, 0)
        assert reaction_packet(packets, FAITH)["actor_id"] == caster
        assert reaction_packet(packets, BARK)["mechanical_effect"] == "round_ac_bonus"
        assert await pools(fight) == before
        state = await fight.reload()
        assert ward_sources(state, ally) == [caster]
        assert not participant(state, ally).bark_skin_active


@pytest.mark.parametrize("fate", [False, True])
async def test_first_faith_caster_wards_the_ally_once(reset_db_pool, fate):
    async with defense_fight(
        "diplomat",
        ally_archetype="warden",
        extra_archetypes=("marshal",),
        library=((0, FAITH), (2, FAITH)),
        fate=fate,
    ) as fight:
        other, ally, first = fight.players
        modifier = await set_target(fight, ally)
        before = await resources(fight, other)
        hp_before = await pools(fight)
        await declare_attacks(fight, ally, BANDIT)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(19 - modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window, original = await open_hit(fight, fate, (19 - modifier, 19, 16))
            assert {o["actor_id"] for o in window["reactions"] if o["id"] == FAITH} == {first, other}
            await spend_faith(fight, first, window)
            withdrawn = await tool_receipt(fight, other, "activate", {"id": FAITH})
            await reload_session(fight)
            budget = (await fight.reload()).reactions_available[other]
            packets = await fight.drain()
        attack = blow(packets)
        assert (attack["target_ac"], attack["hit"], attack["damage"]) == (18, True, original["damage"])
        assert (await pools(fight))[1][0] == hp_before[1][0] - attack["damage"]
        assert withdrawn.is_error and "already warded" in withdrawn.output
        assert not budget["spent"] and await resources(fight, other) == before
        assert reaction_packet(packets, FAITH)["actor_id"] == first
        assert ward_sources(await fight.reload(), ally) == [first]
