from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import (
    SHIELD,
    THOUGHT,
    action_packet,
    declare_attacks,
    defense_fight,
    hp,
    spend,
)
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import declare, strike

import conditions
from check_resolution import D20Roll


@pytest.mark.parametrize("turn", ["declared", "omitted", "stunned"])
async def test_shield_expires_at_own_turn(reset_db_pool, turn):
    async with defense_fight("mage") as fight:
        target, ally = fight.players
        enemy = fight.enemies[0]
        await declare_attacks(fight, target, enemy)
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(17 - self.modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            await spend(fight, SHIELD, stage="pre_roll")
            await fight.drain()
            state = await fight.reload()
            mage = participant(state, target)
            assert mage.shield_spell_active
            state.initiative_order = [ally, target, *fight.enemies]
            participant(state, ally).initiative = 40
            mage.initiative = 39
            if turn == "stunned":
                mage.conditions = conditions.apply_condition(mage.conditions, "stunned", duration=2)
            await fight.persist()
            declarations = [{"actor_id": enemy, **strike(target, action=SWORD)}]
            if turn == "declared":
                declarations.append({"actor_id": target, **strike(enemy)})
            await fight.command("declare_phase", {"declarations": declarations})
            packets = await fight.drain()
        attack = action_packet(packets, enemy, SWORD)
        assert (attack["target_ac"], attack["hit"], attack["damage"]) == (16, True, 8)
        assert await hp(fight) == [92, 100]


async def test_other_reaction_does_not_halve_psychic(reset_db_pool):
    async with defense_fight("mage", "still") as fight:
        (enemy,) = fight.enemies
        action = "Perfect Memory"
        await declare(fight, actor_id=enemy, **strike(fight.players[0], action=action))
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(7 if self.modifier == 12 else 1)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            packets = await spend(fight, SHIELD, stage="pre_roll")
            packets += await fight.drain()
        attack = action_packet(packets, enemy, action)
        assert (attack["target_ac"], attack["hit"], attack["damage"]) == (19, True, 8)
        assert await hp(fight) == [92, 100]


async def test_thought_shield_stops_at_answered_action(reset_db_pool):
    async with defense_fight("whisper", "hollow_warden") as fight:
        target = fight.players[0]
        action = "Reality Fracture"
        await fight.command(
            "declare_phase",
            {"declarations": [{"actor_id": actor, **strike(target, action=action)} for actor in fight.enemies]},
        )
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            packets = await spend(fight, THOUGHT, stage="pre_roll")
            packets += await fight.drain()
        assert [action_packet(packets, actor, action)["damage"] for actor in fight.enemies] == [4, 8]
        assert await hp(fight) == [88, 100]


async def test_shield_stacks_with_ally_guard_without_protecting_the_ally(reset_db_pool):
    async with defense_fight("mage", ally_archetype="cleric") as fight:
        mage, ally = fight.players
        enemy, followup = fight.enemies
        ally_ac = participant(await fight.reload(), ally).ac
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": enemy, **strike(mage, action=SWORD)},
                    {"actor_id": followup, **strike(ally, action=SWORD)},
                ]
            },
        )
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20 - self.modifier)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
        ):
            packets = await spend(fight, SHIELD, stage="pre_roll")
            guard = await tool_receipt(fight, ally, "activate", {"id": "cleric_shield_of_faith"})
            assert not guard.is_error, guard.output
            packets += await fight.drain()
        protected = action_packet(packets, enemy, SWORD)
        exposed = action_packet(packets, followup, SWORD)
        assert (protected["target_ac"], protected["hit"]) == (21, False)
        assert (exposed["target_ac"], exposed["hit"], exposed["damage"]) == (ally_ac, True, 8)
        assert await hp(fight) == [100, 92]
