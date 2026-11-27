"""Shield of Faith checks the struck ally and refuses an existing ward."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import declare_attacks, defense_fight, reload_session
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import blow
from acceptance.test_guardian_intercept import BANDIT, SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_reaction_offers import resources
from acceptance.test_spell_shield_of_faith import FAITH, set_target, spend_faith, ward_sources
from acceptance.test_still_anchors import strike

from check_resolution import D20Roll
from combat_spatial import require_spatial
from combat_structures import THORNWALL, add_wall


@pytest.mark.parametrize("recipient", ["too_far", "self", "wall", "at_range"])
async def test_faith_requires_another_ally_within_thirty_feet(reset_db_pool, recipient):
    async with defense_fight("diplomat", ally_archetype="whisper", library=((0, FAITH),)) as fight:
        caster, ally = fight.players
        target = {"self": caster, "wall": "thornwall"}.get(recipient, ally)
        ac = 16
        if recipient == "wall":
            state = await fight.reload()
            ac = add_wall(state, target, "Thornwall", pos(0, -4), pos(0, 4), kind=THORNWALL).ac
            await fight.persist()
        await set_target(fight, target, ac=ac, distance=35 if recipient == "too_far" else 30)
        before = await resources(fight, caster)
        hp = participant(await fight.reload(), target).hp_current
        await declare_attacks(fight, target, BANDIT)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(ac + 1 - self.modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            window = await open_stage(fight, "post_roll")
            offered = (caster, FAITH) in {(o["actor_id"], o["id"]) for o in window["reactions"]}
            if recipient == "at_range":
                await spend_faith(fight, caster, window)
            else:
                refused = await tool_receipt(fight, caster, "activate", {"id": FAITH})
                await reload_session(fight)
                budget = (await fight.reload()).reactions_available[caster]
            attack = blow(await fight.drain())
        state = await fight.reload()
        if recipient == "at_range":
            assert (attack["target_ac"], attack["hit"], participant(state, target).hp_current) == (18, False, hp)
            assert offered and ward_sources(state, target) == [caster]
        else:
            assert (attack["target_ac"], attack["hit"], participant(state, target).hp_current) == (ac, True, hp - 7)
            assert refused.is_error and not offered
            assert not budget["spent"] and await resources(fight, caster) == before
            assert not ward_sources(state, target)


@pytest.mark.parametrize("same_target", [True, False])
async def test_active_ward_withdraws_faith_only_for_its_recipient(reset_db_pool, same_target):
    async with defense_fight(
        "diplomat", ally_archetype="warden", extra_archetypes=("marshal",), library=((0, FAITH), (2, FAITH))
    ) as fight:
        caster, ally, other = fight.players
        modifier = await set_target(fight, ally)
        before = await resources(fight, other)
        second = ally if same_target else caster
        state = await fight.reload()
        if not same_target:
            require_spatial(state)["positions"]["lookout"] = pos(25, 5)
            await fight.persist()
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": BANDIT, **strike(ally, action=SWORD)},
                    {"actor_id": "lookout", **strike(second, action=SWORD)},
                ]
            },
        )
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(19 - modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        ):
            await spend_faith(fight, caster, await open_stage(fight, "post_roll"))
            result = await fight.command("resolve_phase", {})
            attack = blow(result["packets"])
            assert (attack["target_ac"], attack["hit"]) == (18, True)
            window = result["next"]["waiting_on"]
            if window["stage"] != "post_roll":
                window = await open_stage(fight, "post_roll")
            if not same_target:
                await spend_faith(fight, other, window)
            else:
                refused = await tool_receipt(fight, other, "activate", {"id": FAITH})
                await reload_session(fight)
            followup = blow(await fight.drain(), fight.enemies[1])
        assert (followup["target_ac"], followup["hit"], followup["damage"]) == (18, True, 7)
        state = await fight.reload()
        assert ward_sources(state, ally) == [caster]
        if same_target:
            assert all(o["id"] != FAITH for o in window["reactions"])
            assert refused.is_error and "already warded" in refused.output
            assert await resources(fight, other) == before
        else:
            assert ward_sources(state, second) == [other]
            assert (await resources(fight, other))[0] == before[0] - 2
