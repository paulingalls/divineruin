import pytest
from acceptance.defensive_reactions_harness import defense_fight, hp, reaction_packet, reload_session
from acceptance.disruption_reactions_harness import (
    BARD,
    DOUBT,
    ambush,
    attack_damage,
    attacks,
    dice,
    focus,
    open_stage,
    spend,
)
from acceptance.test_architect_fight import declare_attack
from acceptance.test_bark_skin import blow, keep_original
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory


@pytest.mark.parametrize(("save_face", "saved"), [(18, False), (19, True), (20, True)])
async def test_dissonant_whisper(reset_db_pool, save_face, saved):
    async with ambush(BARD) as fight:
        if saved:
            state = await fight.reload()
            reactor = state.get_participant(fight.players[0])
            assert reactor is not None
            reactor.attributes["charisma"] = 30 if save_face == 20 else 14
            await fight.persist()
        await open_stage(fight, "pre_roll")
        remaining = await spend(fight, BARD)
        with dice(save_face, 18, 4), attack_damage(7, 7):
            packets = await fight.drain()
        hit = blow(packets)
        assert hit["hit"] is saved
        effect = reaction_packet(packets, BARD)
        assert (effect["save_type"], effect["save_dc"], effect["save_roll"], effect["save_modifier"]) == (
            "wisdom",
            21 if save_face == 20 else 13 if saved else 18,
            save_face,
            -2,
        )
        assert (effect["save_total"], effect["save_success"]) == (save_face - 2, saved)
        assert {"rally_bonuses", "success_override"}.isdisjoint(effect)
        assert hit["roll"] == (18 if saved else 4)
        assert await hp(fight) == ([93, 100] if saved else [100, 100])
        assert await focus(fight) == remaining


@pytest.mark.parametrize("saved", [False, True])
async def test_implant_doubt(reset_db_pool, saved):
    async with ambush(DOUBT) as fight:
        with dice(20, 20 if saved else 5, 19, 16), attack_damage(12, 7, 6):
            await open_stage(fight, "post_roll")
            remaining = await spend(fight, DOUBT)
            packets = await fight.drain()
        hit = blow(packets)
        assert hit["roll"] == (20 if saved else 16)
        assert (hit["hit"], hit["critical"], hit["damage"]) == (True, saved, 19 if saved else 6)
        effect = reaction_packet(packets, DOUBT)
        assert (effect["save_type"], effect["save_dc"], effect["save_success"]) == ("wisdom", 15, saved)
        assert await hp(fight) == [100, 81 if saved else 94]
        assert await focus(fight) == remaining
        assert [event["roll"] for event in attacks(fight)] == ([20] if saved else [20, 16])


@pytest.mark.parametrize("ability", [BARD, DOUBT])
async def test_legendary_resistance(reset_db_pool, ability):
    bard = ability == BARD
    async with defense_fight("bard" if bard else "whisper", "hollow_architect") as fight:
        state = await fight.reload()
        (enemy,) = fight.enemies
        architect = state.get_participant(enemy)
        assert architect and architect.action_ledger["legendary resistance"]["remaining"] == 3
        recipient = fight.players[0 if bard else 1]
        await declare_attack(fight, enemy, recipient, "Construct Slam")
        faces = (1, 18, 4) if bard else (18, 1, 17, 4)
        with dice(*faces), attack_damage(7, 3):
            await open_stage(fight, "pre_roll" if bard else "post_roll")
            remaining = await spend(fight, ability)
            packets = await fight.drain()
        effect = reaction_packet(packets, ability)
        assert not effect["save_success"] and "success_override" not in effect
        assert effect["mechanical_effect"] == ("attack_disadvantage" if bard else "attack_rerolled")
        assert not blow(packets, enemy)["hit"]
        architect = (await fight.reload()).get_participant(enemy)
        assert architect and architect.action_ledger["legendary resistance"]["remaining"] == 3
        assert await hp(fight) == [100, 100]
        assert await focus(fight) == remaining


@pytest.mark.parametrize("ability", [BARD, DOUBT])
@pytest.mark.parametrize("resume", ["live", "reload"])
async def test_disruption_save_resumes_once(reset_db_pool, ability, resume):
    bard = ability == BARD
    live = resume == "live"
    async with ambush(ability, fate=True) as fight:
        faces = (*(() if bard else (18,)), 5, *((20, 18) if live and bard else (20,) if live else (18, 4)))
        with dice(*faces) as rolls, attack_damage(7, 7):
            await open_stage(fight, "pre_roll" if bard else "post_roll")
            remaining = await spend(fight, ability)
            paused = await fight.command("resolve_phase", {})
            if "fate_offer" not in paused:
                assert not blow(paused["packets"])["hit"], paused["packets"]
            offer = paused["fate_offer"]
            assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (fight.enemies[0], "save", 5)
            assert await hp(fight) == [100, 100]
            assert await focus(fight) == remaining
            if live:
                args = {"id": "zhael_fates_thread", "offer_id": offer["offer_id"]}
                assert (await fight.command("activate", args))["reroll"]["die"] == 20
                final = await fight.command("activate", {**args, "keep": "reroll"})
                assert "fate_offer" not in final, final.get("fate_offer")
                if final["next"]["waiting_on"]:
                    final["packets"] += await fight.drain()
            else:
                await reload_session(fight)
                replacement = await fight.command("resolve_phase", {})
                offer = replacement["fate_offer"]
                assert (offer["roll_kind"], offer["die"]) == ("attack", 4)
                final = await keep_original(fight, offer)
        assert rolls.call_count == len(faces)
        effect = reaction_packet(final["packets"], ability)
        assert (effect["save_roll"], effect["save_success"]) == (20 if live else 5, live)
        hit = blow(final["packets"])
        assert (hit["roll"], hit["hit"], hit["damage"]) == (18 if live else 4, live, 7 if live else 0)
        event = attacks(fight)[-1]
        assert (event["roll"], event["success"], event["damage"]) == (hit["roll"], hit["hit"], hit["damage"])
        assert await hp(fight) == (([93, 100] if bard else [100, 93]) if live else [100, 100])
        assert await focus(fight) == remaining


@pytest.mark.parametrize("source", ["reactor", "ally"])
async def test_dissonant_whisper_uses_only_reactors_mark_of_justice(reset_db_pool, source):
    from patron_combat_edges import mark_of_justice

    async with ambush(BARD) as fight:
        state = await fight.reload()
        reactor, ally = fight.players
        state, receipt = mark_of_justice(state, reactor if source == "reactor" else ally, target_id=fight.enemies[0])
        assert receipt["marked_target"]["id"] == fight.enemies[0]
        enemy = state.get_participant(fight.enemies[0])
        assert enemy
        enemy.attributes["wisdom"] = 12
        fight.sd.combat_state = state
        await fight.persist()
        await open_stage(fight, "pre_roll")
        await spend(fight, BARD)
        with dice(17, 18, 4), attack_damage(7, 7):
            packets = await fight.drain()
        saved = source == "ally"
        assert blow(packets)["hit"] is saved
        effect = reaction_packet(packets, BARD)
        assert (effect["save_modifier"], effect["save_success"]) == (1 if saved else -1, saved)


async def test_implant_doubt_reroll_and_concentration_resume_once(reset_db_pool):
    from db_mutations_concentration import update_player_concentration

    async with ambush(DOUBT, fate=True) as fight:
        enemy = fight.enemies[0]
        recipient = fight.players[1]
        spell = "divine_bless"
        await update_player_concentration(recipient, spell, conn=fight.pool)
        fight.sd.member_state(recipient).concentration.spell_id = spell
        with dice(20, 5, 19, 16, 1) as rolls, attack_damage(12, 7, 6):
            await open_stage(fight, "post_roll")
            remaining = await spend(fight, DOUBT)
            save = await fight.command("resolve_phase", {})
            replacement = await keep_original(fight, save["fate_offer"])
            offer = replacement["fate_offer"]
            assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (enemy, "attack", 16)
            assert [(event["roll"], event["damage"]) for event in attacks(fight)] == [(20, 19)]
            assert await hp(fight) == [100, 100]
            await reload_session(fight)
            concentration = await fight.command("resolve_phase", {})
            offer = concentration["fate_offer"]
            assert (offer["roller_id"], offer["roll_kind"], offer["die"]) == (recipient, "save", 1)
            assert await hp(fight) == [100, 94]
            assert [(event["roll"], event["damage"]) for event in attacks(fight)] == [(20, 19), (16, 6)]
            await reload_session(fight)
            packets = await fight.drain()
        hit = blow(packets)
        assert (hit["roll"], hit["damage"], hit["critical"], hit["concentration_broken"]) == (16, 6, False, spell)
        assert not reaction_packet(packets, DOUBT)["save_success"]
        assert rolls.call_count == 5
        assert [(event["roll"], event["damage"]) for event in attacks(fight)] == [(20, 19), (16, 6)]
        assert await hp(fight) == [100, 94]
        assert await focus(fight) == remaining


async def test_two_whispers_keep_spend_order_across_reload(reset_db_pool):
    from acceptance.defensive_reactions_harness import player_row
    from acceptance.test_guardian_intercept import tool_receipt

    async with ambush(DOUBT, fate=True, ally_archetype="whisper") as fight:
        remaining = {actor: (await player_row(actor))["focus"]["current"] - 2 for actor in fight.players}
        with dice(18, 4, 19, 16, 5, 17, 4), attack_damage(7, 9):
            await open_stage(fight, "post_roll")
            state = await fight.reload()
            first, second = reversed([actor for actor in state.reactions_available if actor in fight.players])
            for actor in (first, second):
                receipt = await tool_receipt(fight, actor, "activate", {"id": DOUBT})
                assert not receipt.is_error, receipt.output
            await reload_session(fight)
            # The second save must carry its own checkpoint after the first result settled.
            initial = await fight.command("resolve_phase", {})
            assert initial["fate_offer"]["die"] == 4
            first_replacement = await keep_original(fight, initial["fate_offer"])
            assert first_replacement["fate_offer"]["die"] == 16
            later = await keep_original(fight, first_replacement["fate_offer"])
            assert (later["fate_offer"]["roll_kind"], later["fate_offer"]["die"]) == ("save", 5)
            await reload_session(fight)
            replacement = await fight.command("resolve_phase", {})
            final = await keep_original(fight, replacement["fate_offer"])
        receipts = [p for p in final["packets"] if p.get("ability_id") == DOUBT]
        assert [(p["actor_id"], p["save_success"], p["save_roll"]) for p in receipts] == [
            (first, False, 4),
            (second, False, 5),
        ]
        assert not blow(final["packets"])["hit"]
        assert await hp(fight) == [100, 100]
        for actor in fight.players:
            assert (await player_row(actor))["focus"]["current"] == remaining[actor]


@pytest.mark.parametrize(
    ("archetype", "defense", "expected"),
    [
        ("warrior", "warrior_brace_for_impact", 3),
        ("rogue", "rogue_uncanny_dodge", 4),
    ],
)
async def test_replacement_keeps_damage_reductions(reset_db_pool, archetype, defense, expected):
    from unittest.mock import patch

    from acceptance._capstone_helpers import _damage_die
    from acceptance.test_guardian_intercept import tool_receipt

    async with ambush(DOUBT, ally_archetype=archetype) as fight:
        with dice(18, 5, 19, 16), attack_damage(12, 8), patch("dice.roll", return_value=_damage_die(3)) as brace_die:
            await open_stage(fight, "post_roll")
            await spend(fight, DOUBT)
            receipt = await tool_receipt(fight, fight.players[1], "activate", {"id": defense})
            assert not receipt.is_error, receipt.output
            packets = await fight.drain()
        hit = blow(packets)
        assert (hit["roll"], hit["damage"]) == (16, expected)
        assert attacks(fight)[-1]["damage"] == expected
        assert await hp(fight) == [100, 100 - expected]
        if archetype == "warrior":
            brace_die.assert_called_once_with("1d6")
            assert reaction_packet(packets, defense)["damage_prevented"] == 5
