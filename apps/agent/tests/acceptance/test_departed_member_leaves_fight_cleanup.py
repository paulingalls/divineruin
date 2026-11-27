import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance import test_departed_member_leaves_fight as departure
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import move
from acceptance.defensive_reactions_harness import SPELL, defense_fight, player_row
from acceptance.disruption_reactions_harness import DOUBT, ambush, attack_damage, dice, open_stage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, enter, pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_paladin_oath_swear import patch_player
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.turn_undead_harness import TurnFight
from acceptance.turn_undead_harness import fight as fight

import db_mutations_concentration


async def test_departed_turner_frees_the_undead_to_fight(fight: TurnFight) -> None:
    await fight.enter({"skeleton": ("undead", 4)}, ally=True)
    caster, survivor = fight.players
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        turned = fight.cast(await fight.phase(cast=True))["turn_undead"]
    assert {row["target_id"]: row["outcome"] for row in turned}["skeleton"] == "frightened"
    async with departure.departed(fight, caster):
        fight.players = [survivor]  # The harness speaks as its first player.
        hp = (await player_row(survivor))["hp"]["current"]
        await departure.declare(fight, {**fight.attack("skeleton"), "target_id": survivor})
        with (
            patch("check_resolution.dice_roll", return_value=_d20(18)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            (swing,) = [p for p in await fight.drain() if p["actor_id"] == "skeleton" and "hit" in p]
        assert swing["hit"] and not swing.get("fled")
        assert (await player_row(survivor))["hp"]["current"] == hp - swing["damage"]


async def test_landed_entomb_on_a_departed_target_keeps_its_receipt(reset_db_pool) -> None:
    from acceptance.test_slippery_restrain import advance
    from acceptance.test_slippery_restrain import declare as declare_entomb

    harness = MawlingHarness()
    try:
        await harness.prepare((5, 5), companion=None, location=WORKS)
        host, guest = harness.players
        await patch_player(guest, **{"class": "rogue"})
        state = await enter(harness)
        owner = departure.present(state.architect_encounter)["owner_id"]
        departure.present(state.spatial)["positions"].update({guest: pos(5), host: pos(40), owner: pos(0)})
        await harness.persist()
        await declare_entomb(harness, owner, guest, "Entomb")
        with patch("check_resolution.dice_roll", return_value=_d20(1)), patch("combat_recharge.roll") as recharge:
            recharge.return_value = SimpleNamespace(total=5)
            assert departure.present((await advance(harness, expect_condition_window=True))[1])["target_id"] == guest
            async with departure.departed(harness, guest):
                packets = await harness.drain()
        (cast,) = [p for p in packets if p["actor_id"] == owner and p.get("target_id") == guest]
        landed = (cast.get("outcome"), cast.get("condition_inflicted"), cast.get("save_success"))
        assert landed == (None, "restrained", False)
    finally:
        await harness.close()


@pytest.mark.parametrize("held_save", ["disruption", "concentration"])
async def test_departed_disruptors_doubt_is_neither_settled_nor_recorded(reset_db_pool, held_save: str) -> None:
    async with ambush(DOUBT, fate=True, extra_archetypes=("whisper",)) as fight:
        _, recipient, reactor = fight.players
        state = await fight.reload()
        participant(state, reactor).attributes.update(charisma=24, intelligence=18)
        await fight.persist()
        concentration = held_save == "concentration"
        if concentration:
            await db_mutations_concentration.update_player_concentration(recipient, "divine_bless", conn=fight.pool)
            fight.sd.member_state(recipient).concentration.spell_id = "divine_bless"
        with dice(20, 5, 19, 16, 1, 1, 1), attack_damage(12, 7, 6):
            await open_stage(fight, "post_roll")
            assert not (await tool_receipt(fight, reactor, "activate", {"id": DOUBT})).is_error
            offer = (await fight.command("resolve_phase", {}))["fate_offer"]
            if concentration:
                offer = (await keep_original(fight, (await keep_original(fight, offer))["fate_offer"]))["fate_offer"]
            assert offer["roller_id"] == (recipient if concentration else fight.enemies[0])
            hp, reactor_row = (await player_row(recipient))["hp"]["current"], await player_row(reactor)
            async with departure.departed(fight, reactor):
                packets = (await keep_original(fight, offer))["packets"] if concentration else await fight.drain()
        (hit,) = [p for p in packets if p["actor_id"] == fight.enemies[0] and "damage" in p]
        assert hit["damage"] == (6 if concentration else 19)
        assert not [p for p in packets if p.get("ability_id") == DOUBT]
        assert await player_row(reactor) == reactor_row
        assert (await player_row(recipient))["hp"]["current"] == hp - (0 if concentration else hit["damage"])


@pytest.mark.parametrize("fallen", [False, True])
async def test_departure_drops_a_paused_wrap_save(reset_db_pool, fallen: bool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        host, guest = fight.players
        state = await fight.reload()
        roller = host if fallen else guest
        participant(state, roller).conditions = [{"type": "frightened", "source": fight.enemies[0], "duration": None}]
        if fallen:
            participant(state, guest).hp_current, participant(state, guest).is_fallen = 0, True
        await fight.persist()
        await departure.defend_all(fight)
        with departure.d20(5):
            for _ in range(4):
                if offer := (await fight.command("resolve_phase", {})).get("fate_offer"):
                    break
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", roller)
            assert (
                guest in departure.present((await fight.reload()).wrap_continuation)["wrap"]["death_saves_due"]
            ) is fallen
            async with departure.departed(fight, guest):
                result = await (keep_original(fight, offer) if fallen else fight.command("resolve_phase", {}))
                state = await fight.reload()
                assert (result.get("fate_offer"), state.round_number, state.wrap_continuation) == (None, 2, None)
                departure.assert_departed(state, guest)


async def test_departure_drops_a_paused_inner_fire(reset_db_pool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        guest = fight.players[1]
        await patch_player(guest, race="draethar")
        fight.sd.member_state(guest).concentration.spell_id = SPELL
        await db_mutations_concentration.update_player_concentration(guest, SPELL, conn=fight.pool)
        with departure.d20(5):
            receipt = await tool_receipt(fight, guest, "activate", {"id": "draethar_inner_fire"})
            assert json.loads(receipt.output)["fate_offer"]["roller_id"] == guest
            async with departure.departed(fight, guest):
                await departure.defend_all(fight)
                await fight.drain()
                assert (await fight.reload()).round_number == 2


async def test_departed_movers_held_opportunity_offer_is_withdrawn(reset_db_pool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        host, guest = fight.players
        foe, lookout = fight.enemies
        state = await fight.reload()
        departure.present(state.spatial)["positions"].update(
            {host: pos(30), guest: pos(0), foe: pos(-5), lookout: pos(-60)}
        )
        await fight.persist()
        await departure.declare(fight, move(guest, 25))
        with departure.d20(16):
            assert (await fight.command("resolve_phase", {}))["fate_offer"]["roller_id"] == foe
            hp = (await player_row(guest))["hp"]
            async with departure.departed(fight, guest):
                assert all(p.get("target_id") != guest for p in await fight.drain())
                assert (await player_row(guest))["hp"] == hp
                state = await fight.reload()
                assert state.round_number == 2
                departure.assert_departed(state, guest)
