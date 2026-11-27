import pytest
from acceptance.defensive_reactions_harness import hp, reaction_packet, reload_session
from acceptance.disruption_reactions_harness import (
    DOUBT,
    ambush,
    attack_damage,
    attacks,
    dice,
    focus,
    open_stage,
    spend,
)
from acceptance.test_bark_skin import blow, keep_original
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory


@pytest.mark.parametrize("route", ["immediate", "reload"])
async def test_implant_doubt_keeps_miss(reset_db_pool, route):
    reload = route == "reload"
    async with ambush(DOUBT, fate=reload) as fight:
        with dice(18, 5, 17, 4), attack_damage(7, 7):
            await open_stage(fight, "post_roll")
            remaining = await spend(fight, DOUBT)
            if reload:
                paused = await fight.command("resolve_phase", {})
                if offer := paused.get("fate_offer"):
                    assert (offer["roller_id"], offer["roll_kind"]) == (fight.enemies[0], "save")
                    await reload_session(fight)
                    replacement = await fight.command("resolve_phase", {})
                    packets = (await keep_original(fight, replacement["fate_offer"]))["packets"]
                else:
                    packets = paused["packets"]
            else:
                packets = await fight.drain()
        hit = blow(packets)
        assert (hit["roll"], hit["hit"], hit["damage"], hit["critical"]) == (4, False, 0, False)
        assert not reaction_packet(packets, DOUBT)["save_success"]
        event = attacks(fight)[-1]
        assert (event["roll"], event["success"], event["damage"], event["critical"]) == (4, False, 0, False)
        assert await hp(fight) == [100, 100]
        assert fight.sd.recent_events.count("Bandit attacks Acceptance Tester: miss, 0 damage") == 1
        assert await focus(fight) == remaining


@pytest.mark.parametrize(
    ("stage", "face", "reason"),
    [
        ("pre_roll", 18, "post-roll"),
        ("post_roll", 4, "successful attack roll"),
    ],
)
async def test_implant_doubt_refuses_wrong_attack_window(reset_db_pool, stage, face, reason):
    from acceptance.disruption_reactions_harness import activate

    # A bard supplies the legitimate targeting window and a skirmisher supplies the miss window.
    async with ambush(DOUBT, ally_archetype="bard" if stage == "pre_roll" else "skirmisher") as fight:
        with dice(face), attack_damage(7):
            window = await open_stage(fight, stage)
            assert "on_enemy_action" in window["triggers"]
            before = await fight.snapshot()
            receipt = await activate(fight, DOUBT)
            assert receipt.is_error and reason in receipt.output
            assert await fight.snapshot() == before
            assert DOUBT not in {reaction["id"] for reaction in window["reactions"]}


async def test_implant_doubt_refuses_serenitys_touch(reset_db_pool):
    from acceptance.defensive_reactions_harness import defense_fight
    from acceptance.disruption_reactions_harness import activate
    from acceptance.test_still_anchors import declare, strike

    async with defense_fight("whisper", "still") as fight:
        (enemy,) = fight.enemies
        await declare(fight, actor_id=enemy, **strike(fight.players[0], action="Serenity's Touch"))
        window = await open_stage(fight, "pre_roll")
        assert window["action"] == "Serenity's Touch"
        before = await fight.snapshot()
        receipt = await activate(fight, DOUBT)
        assert receipt.is_error and "only answers enemy attack rolls" in receipt.output
        assert await fight.snapshot() == before
        assert DOUBT not in {reaction["id"] for reaction in window["reactions"]}


async def test_implant_doubt_refuses_rejection(reset_db_pool):
    from types import SimpleNamespace
    from unittest.mock import patch

    from acceptance.defensive_reactions_harness import defense_fight
    from acceptance.disruption_reactions_harness import activate
    from acceptance.test_still_anchors import declare, spell

    async with defense_fight("whisper", "still") as fight:
        (enemy,) = fight.enemies
        with patch("combat_recharge.roll", return_value=SimpleNamespace(total=6)):
            await declare(fight, kind="defend", reshape=[])
            await fight.drain()
        await declare(fight, actor_id=enemy, **spell("Rejection"))
        step = await fight.command("resolve_phase", {})
        assert step["next"]["waiting_on"] is None
        before = await fight.snapshot()
        receipt = await activate(fight, DOUBT)
        assert receipt.is_error and "only answers enemy attack rolls" in receipt.output
        assert await fight.snapshot() == before
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=20)):
            packets = await fight.drain()
        assert any(packet.get("action") == "Rejection" and packet["resolved"] for packet in packets)
        assert all(packet.get("ability_id") != DOUBT for packet in packets)
        encounter = (await fight.reload()).still_encounter
        assert encounter is not None and encounter["pending_rejection"] is None


async def test_bard_disruption_requires_enemy_hearing(reset_db_pool):
    from acceptance.disruption_reactions_harness import BARD, activate

    import conditions

    async with ambush(BARD, ally_archetype="cleric") as fight:
        state = await fight.reload()
        enemy = state.get_participant(fight.enemies[0])
        assert enemy
        enemy.conditions = conditions.apply_condition(enemy.conditions, "deafened")
        await fight.persist()
        with dice(18), attack_damage(7):
            window = await open_stage(fight, "pre_roll")
            assert BARD not in {reaction["id"] for reaction in window["reactions"]}
            before = await fight.snapshot()
            receipt = await activate(fight, BARD)
            assert receipt.is_error and "cannot hear" in receipt.output
            assert await fight.snapshot() == before
            assert blow(await fight.drain())["hit"]


@pytest.mark.parametrize("advantage", [False, True])
async def test_bard_disruption_stays_on_triggering_attack(reset_db_pool, advantage):
    from acceptance.disruption_reactions_harness import BARD

    import conditions

    async with ambush(BARD, followup=True) as fight:
        enemy, followup = fight.enemies
        if advantage:
            state = await fight.reload()
            attacker = state.get_participant(enemy)
            assert attacker
            attacker.conditions = conditions.apply_condition(attacker.conditions, "precise_strike")
            await fight.persist()
        with dice(*((18, 17, 18) if advantage else (18, 17, 4, 18))), attack_damage(7, 7):
            await open_stage(fight, "pre_roll")
            await spend(fight, BARD)
            packets = await fight.drain()
        hit = blow(packets, enemy)
        assert (hit["hit"], hit["roll"]) == (advantage, 17 if advantage else 4)
        later = blow(packets, followup)
        assert (later["hit"], later["roll"]) == (True, 18)
        assert "attack_disadvantage_source" not in later


async def test_implant_doubt_miss_opens_riposte_after_reload(reset_db_pool):
    from acceptance.test_guardian_intercept import tool_receipt

    from reaction_spend import RIPOSTE

    async with ambush(DOUBT, ally_archetype="skirmisher") as fight:
        with dice(18, 5, 17, 4, 18), attack_damage(7, 4):
            await open_stage(fight, "post_roll")
            await spend(fight, DOUBT)
            missed = await fight.command("resolve_phase", {})
            assert missed["next"]["waiting_on"]["stage"] == "post_reaction_miss"
            assert [(event["roll"], event["success"]) for event in attacks(fight)] == [(18, True), (4, False)]
            await reload_session(fight)
            receipt = await tool_receipt(fight, fight.players[1], "activate", {"id": RIPOSTE})
            assert not receipt.is_error, receipt.output
            packets = await fight.drain()
        counter = reaction_packet(packets, RIPOSTE)
        assert counter["mechanical_effect"] == "riposte" and counter["counter_attack"]["damage"] > 0
        assert not blow(packets)["hit"]
        assert await hp(fight) == [100, 100]


async def test_fate_held_reroll_miss_opens_riposte_once_after_reload(reset_db_pool):
    from acceptance.test_bark_skin import keep_original

    async with ambush(DOUBT, fate=True, ally_archetype="skirmisher") as fight:
        with dice(18, 5, 17, 4, 18), attack_damage(7, 4):
            await open_stage(fight, "post_roll")
            await spend(fight, DOUBT)
            save = await fight.command("resolve_phase", {})
            held = await keep_original(fight, save["fate_offer"])
            assert (held["fate_offer"]["roll_kind"], held["fate_offer"]["die"]) == ("attack", 4)
            await reload_session(fight)
            # The resumed settle finishes the held reroll that missed; this call never saw it start.
            window = (await fight.command("resolve_phase", {}))["next"]["waiting_on"]
            assert window["stage"] == "post_reaction_miss"
            assert [r["actor_id"] for r in window["reactions"]] == [fight.players[1]]
            await reload_session(fight)
            stages = []
            for _ in range(6):
                if (await fight.reload()).round_number != 1:
                    break
                waiting = (await fight.command("resolve_phase", {}))["next"]["waiting_on"]
                stages.append(waiting and waiting["stage"])
        assert "post_reaction_miss" not in stages
        assert [(event["roll"], event["success"]) for event in attacks(fight)][:2] == [(18, True), (4, False)]
        assert await hp(fight) == [100, 100]


async def test_implant_doubt_does_not_reroll_a_hit_bark_skin_turned_aside(reset_db_pool):
    from acceptance.test_guardian_intercept import tool_receipt

    async with ambush(DOUBT, ally_archetype="warden") as fight:
        with dice(12, 5, 19, 16), attack_damage(8, 6):
            await open_stage(fight, "post_roll")
            remaining = await spend(fight, DOUBT)
            bark = await tool_receipt(fight, fight.players[1], "activate", {"id": "warden_bark_skin"})
            assert not bark.is_error, bark.output
            packets = await fight.drain()
        attack = blow(packets)
        assert (attack["hit"], attack["roll"], attack["damage"]) == (False, 12, 0)
        doubt = reaction_packet(packets, DOUBT)
        assert doubt["mechanical_effect"] is None and "already misses" in doubt["reason"]
        assert "save_roll" not in doubt
        assert await focus(fight) == remaining


async def test_bard_disruption_rechecks_hearing_at_delivery(reset_db_pool):
    from acceptance.disruption_reactions_harness import BARD

    import conditions

    async with ambush(BARD) as fight:
        await open_stage(fight, "pre_roll")
        remaining = await spend(fight, BARD)
        state = await fight.reload()
        enemy = state.get_participant(fight.enemies[0])
        assert enemy
        enemy.conditions = conditions.apply_condition(enemy.conditions, "deafened")
        await fight.persist()
        with dice(18, 19, 4), attack_damage(7):
            packets = await fight.drain()
        assert blow(packets)["hit"]
        effect = reaction_packet(packets, BARD)
        assert effect["mechanical_effect"] is None and "cannot hear" in effect["reason"]
        assert await focus(fight) == remaining


async def test_bard_disruption_yields_to_objection(reset_db_pool):
    from unittest.mock import patch

    from acceptance.disruption_reactions_harness import BARD
    from acceptance.test_guardian_intercept import tool_receipt

    async with ambush(BARD, ally_archetype="diplomat") as fight:
        await open_stage(fight, "pre_roll")
        remaining = await spend(fight, BARD)
        objection = await tool_receipt(fight, fight.players[1], "activate", {"id": "diplomat_objection"})
        assert not objection.is_error, objection.output
        with patch("combat_reaction_contest.random.randint", side_effect=[20, 1]):
            packets = await fight.drain()
        assert reaction_packet(packets, "diplomat_objection")["mechanical_effect"] == "action_hesitated"
        whisper = reaction_packet(packets, BARD)
        assert whisper["mechanical_effect"] is None and "Objection" in whisper["reason"]
        assert not attacks(fight)
        assert await focus(fight) == remaining


async def test_implant_doubt_refuses_a_legacy_provisional_attack(reset_db_pool):
    from acceptance.disruption_reactions_harness import activate

    async with ambush(DOUBT) as fight:
        with dice(18, 5, 17, 4), attack_damage(7):
            await open_stage(fight, "post_roll")
            state = await fight.reload()
            del state.held_actions[0]["attack_context"]
            await fight.persist()
            before = await fight.snapshot()
            refused = await activate(fight, DOUBT)
            assert refused.is_error and "saved reroll context" in refused.output
            assert await fight.snapshot() == before
            hit = blow(await fight.drain())
        assert (hit["roll"], hit["hit"], hit["damage"]) == (18, True, 7)


async def test_dissonant_whisper_refuses_an_automatic_ability(reset_db_pool):
    from acceptance.defensive_reactions_harness import defense_fight
    from acceptance.disruption_reactions_harness import BARD, activate
    from acceptance.test_still_anchors import declare, strike

    async with defense_fight("bard", "still", ally_archetype="cleric") as fight:
        (enemy,) = fight.enemies
        await declare(fight, actor_id=enemy, **strike(fight.players[0], action="Serenity's Touch"))
        window = await open_stage(fight, "pre_roll")
        assert window["action"] == "Serenity's Touch"
        before = await fight.snapshot()
        receipt = await activate(fight, BARD)
        assert receipt.is_error and "only answers enemy attack rolls" in receipt.output
        assert await fight.snapshot() == before
        assert BARD not in {reaction["id"] for reaction in window["reactions"]}
