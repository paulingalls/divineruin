from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.defensive_reactions_harness import (
    BRACE,
    CHOIR,
    SHIELD,
    SPELL,
    THOUGHT,
    action_packet,
    declare_attacks,
    defense_fight,
    hp,
    player_row,
    reaction_packet,
    reload_session,
    spend,
)
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import INTERCEPT, SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import declare, strike

from check_resolution import D20Roll


@pytest.mark.parametrize(("incoming", "expected", "constitution"), [(9, 4, 14), (3, 0, 14), (9, 9, 2)])
async def test_brace_reduces_triggering_hit(reset_db_pool, incoming, expected, constitution):
    for use_reaction in (False, True):
        async with defense_fight("warrior", constitution=constitution) as fight:
            enemy, followup = fight.enemies
            target = fight.players[0]
            await declare_attacks(fight, target)
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(incoming)),
                patch("dice.roll", return_value=_damage_die(3)),
            ):
                packets = await spend(fight, BRACE, stage="post_roll") if use_reaction else []
                packets += await fight.drain()
            damage = expected if use_reaction else incoming
            assert action_packet(packets, enemy, SWORD)["damage"] == damage
            assert action_packet(packets, followup, SWORD)["damage"] == incoming
            assert await hp(fight) == [100 - damage - incoming, 100]
            if use_reaction:
                assert reaction_packet(packets, BRACE)["damage_reduction"] == (5 if constitution == 14 else 0)
                assert reaction_packet(packets, BRACE)["damage_prevented"] == incoming - expected


@pytest.mark.parametrize("margin", [1, 2])
async def test_shield_changes_trigger_and_followup(reset_db_pool, margin):
    for use_reaction in (False, True):
        async with defense_fight("mage") as fight:
            target = fight.players[0]
            await declare_attacks(fight, target)
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16 + margin - self.modifier)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
            ):
                packets = await spend(fight, SHIELD, stage="pre_roll") if use_reaction else []
                packets += await fight.drain()
            for actor in fight.enemies:
                attack = action_packet(packets, actor, SWORD)
                assert (attack["target_ac"], attack["hit"], attack["damage"]) == (
                    (19, False, 0) if use_reaction else (16, True, 8)
                )
            assert await hp(fight) == ([100, 100] if use_reaction else [84, 100])


@pytest.mark.parametrize(
    ("action", "intercept"), [("Perfect Memory", False), ("Perfect Memory", True), ("Serenity's Touch", False)]
)
async def test_thought_shield_still_actions(reset_db_pool, action, intercept):
    for use_reaction in (False, True):
        async with defense_fight("whisper", "still") as fight:
            (enemy,) = fight.enemies
            await declare(fight, actor_id=enemy, **strike(fight.players[0], action=action))
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(8 if self.modifier == 12 else 1)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(8)),
                patch("dice.roll", return_value=_damage_die(8)),
            ):
                packets = await spend(fight, THOUGHT, stage="pre_roll") if use_reaction else []
                if intercept:
                    for _ in range(3):
                        opened = await fight.command("resolve_phase", {})
                        packets.extend(opened["packets"])
                        if (window := opened["next"]["waiting_on"]) and window["stage"] == "post_roll":
                            assert INTERCEPT in {r["id"] for r in window["reactions"]}
                            break
                    else:
                        raise AssertionError("No Intercept window")
                    receipt = await tool_receipt(fight, fight.players[1], "activate", {"id": INTERCEPT})
                    assert not receipt.is_error, receipt.output
                packets += await fight.drain()
            result = action_packet(packets, enemy, action)
            assert result["save_dc"] == 20
            if action == "Serenity's Touch":
                assert result["charmed"] and not result["save_success"] and "hit" not in result
            damage = 4 if use_reaction and not intercept else 8
            assert result["damage"] == damage
            assert await hp(fight) == ([100, 92] if intercept else [100 - damage, 100])
            if use_reaction:
                assert reaction_packet(packets, THOUGHT)["mechanical_effect"] == (
                    None if intercept else "damage_halved"
                )


@pytest.mark.parametrize(("archetype", "ability"), [("whisper", THOUGHT), ("mage", SHIELD)])
async def test_memory_scream_protects_only_the_spender(reset_db_pool, archetype, ability):
    for use_reaction in (False, True):
        async with defense_fight(archetype, CHOIR) as fight:
            enemy = fight.enemies[0]
            target, ally = fight.players
            await declare(fight, actor_id=enemy, **strike(target, action="Memory Scream"))
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(2)),
                patch("combat_enemy_action.dice_roll", return_value=_damage_die(8)),
            ):
                packets = await spend(fight, ability, stage="pre_roll") if use_reaction else []
                packets += await fight.drain()
            result = action_packet(packets, enemy, "Memory Scream")
            damage = 4 if use_reaction and ability == THOUGHT else 8
            assert {r["target_id"]: (r["damage"], r["save_success"]) for r in result["targets"]} == {
                target: (damage, False),
                ally: (8, False),
            }
            assert await hp(fight) == [100 - damage, 92]
            if use_reaction and ability == SHIELD:
                assert not participant(await fight.reload(), target).shield_spell_active
                receipt = reaction_packet(packets, ability)
                assert receipt["mechanical_effect"] is None and "attack rolls" in receipt["reason"]


@pytest.mark.parametrize(
    ("enemy_type", "action", "d20", "incoming", "damage", "reason"),
    [
        ("bandit", SWORD, 15, 8, 8, "Thought Shield only reduces psychic damage"),
        ("still", "Perfect Memory", 1, 8, 0, "dealt no damage to the character who spent it"),
    ],
)
async def test_thought_shield_receipt_says_why_nothing_was_prevented(
    reset_db_pool, enemy_type, action, d20, incoming, damage, reason
):
    for use_reaction in (False, True):
        async with defense_fight("whisper", enemy_type) as fight:
            enemy = fight.enemies[0]
            await declare(fight, actor_id=enemy, **strike(fight.players[0], action=action))
            with (
                patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1 if self.dc == 20 else d20)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(incoming)),
                patch("dice.roll", return_value=_damage_die(incoming)),
            ):
                packets = await spend(fight, THOUGHT, stage="pre_roll") if use_reaction else []
                packets += await fight.drain()
            assert action_packet(packets, enemy, action)["damage"] == damage
            assert await hp(fight) == [100 - damage, 100]
            if use_reaction:
                receipt = reaction_packet(packets, THOUGHT)
                assert receipt["mechanical_effect"] is None and reason in receipt["reason"]
                assert ("only reduces" in receipt["reason"]) != ("no damage" in receipt["reason"])


async def test_brace_preserves_typed_bonus_damage(reset_db_pool):
    async with defense_fight("warrior", "hollow_knight") as fight:
        enemy = fight.enemies[0]
        await declare(fight, actor_id=enemy, **strike(fight.players[0], action="Corrupted Blade"))
        with (
            patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(15)),
            patch("check_resolution_attack.dice_roll", side_effect=[_damage_die(3), _damage_die(6)]),
            patch("dice.roll", return_value=_damage_die(3)),
        ):
            packets = await spend(fight, BRACE, stage="post_roll")
            packets += await fight.drain()
        attack = action_packet(packets, enemy, "Corrupted Blade")
        assert (attack["damage"], attack["bonus_damage"], attack["bonus_damage_type"]) == (4, 4, "necrotic")
        assert await hp(fight) == [96, 100]


@pytest.mark.parametrize(
    ("archetype", "ability", "enemy_type", "action", "expected"),
    [
        ("warrior", BRACE, "bandit", SWORD, 4),
        ("mage", SHIELD, "bandit", SWORD, 8),
        ("whisper", THOUGHT, "still", "Perfect Memory", 4),
        ("whisper", THOUGHT, "still", "Serenity's Touch", 4),
    ],
)
async def test_spent_defense_survives_fate_reload(reset_db_pool, archetype, ability, enemy_type, action, expected):
    async with defense_fight(archetype, enemy_type, fate=True) as fight:
        enemy = fight.enemies[0]
        target = fight.players[0]
        round_number = (await fight.reload()).round_number
        ally_focus = (await player_row(fight.players[1]))["focus"]
        focus_before = (await player_row(target))["focus"]["current"]
        await declare(fight, actor_id=enemy, **strike(target, action=action))
        with (
            patch.object(
                D20Roll, "roll", lambda self, _rng=None: self.evaluate(19 - self.modifier if self.dc in (16, 19) else 7)
            ),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(9 if ability == BRACE else 8)),
            patch("dice.roll", return_value=_damage_die(3 if ability == BRACE else 8)),
        ):
            packets = await spend(fight, ability, stage="post_roll" if ability == BRACE else "pre_roll")
            paused = await fight.command("resolve_phase", {})
            packets.extend(paused["packets"])
            offer = paused["fate_offer"]
            before_resume = await hp(fight)
            expected_kind = "save" if ability == BRACE or action == "Serenity's Touch" else "attack"
            assert (offer["roll_kind"], offer["roller_id"]) == (
                expected_kind,
                target if expected_kind == "save" else enemy,
            )
            assert before_resume == ([100 - expected, 100] if expected_kind == "save" else [100, 100])
            await reload_session(fight)
            offer = None
            for _ in range(10):
                result = await keep_original(fight, offer) if offer else await fight.command("resolve_phase", {})
                packets.extend(result["packets"])
                offer = result.get("fate_offer")
                if (await fight.reload()).round_number > round_number:
                    break
            else:
                raise AssertionError("Fate-held action did not settle")
        attack = action_packet(packets, enemy, action)
        assert attack["damage"] == expected
        assert await hp(fight) == [100 - expected, 100]
        assert (
            reaction_packet(packets, ability)["mechanical_effect"]
            == {BRACE: "damage_reduced", SHIELD: "target_ac_bonus", THOUGHT: "damage_halved"}[ability]
        )
        if ability == SHIELD:
            assert attack["target_ac"] == 19
        if action == "Serenity's Touch":
            assert attack["charmed"] and not attack["save_success"]
        assert attack["concentration_broken"] == SPELL
        assert (await player_row(fight.players[1]))["focus"] == ally_focus
        assert (await player_row(target))["focus"]["current"] == focus_before - (ability != BRACE)
