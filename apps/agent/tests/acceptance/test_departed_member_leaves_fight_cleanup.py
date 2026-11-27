import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import move
from acceptance.defensive_reactions_harness import SPELL, defense_fight, player_row
from acceptance.disruption_reactions_harness import DOUBT, ambush, attack_damage, dice, open_stage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_entomb import seal
from acceptance.test_architect_fight import WORKS, enter, pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_departed_member_leaves_fight import assert_departed, depart
from acceptance.test_guardian_intercept import tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_paladin_oath_swear import patch_player
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.turn_undead_harness import TurnFight
from acceptance.turn_undead_harness import fight as turn_fight  # noqa: F401  (entomb owns "fight")

import db_mutations_concentration
from check_resolution import D20Roll


def defend_all(state) -> dict:
    return {"declarations": [{"kind": "defend", "actor_id": p.id, "reshape": []} for p in state.participants]}


async def test_departed_turner_frees_the_undead_to_fight(turn_fight: TurnFight) -> None:  # noqa: F811
    await turn_fight.enter({"skeleton": ("undead", 4)}, ally=True)
    caster, survivor = turn_fight.players
    with patch("check_resolution.dice_roll", return_value=_d20(2)):
        turned = turn_fight.cast(await turn_fight.phase(cast=True))["turn_undead"]
    assert {row["target_id"]: row["outcome"] for row in turned}["skeleton"] == "frightened"
    lifecycle = await depart(turn_fight, caster)
    turn_fight.players = [survivor]  # The harness speaks as its first player.
    try:
        assert_departed(await turn_fight.reload(), caster)
        before = (await player_row(survivor))["hp"]["current"]
        swing = {**turn_fight.attack("skeleton"), "target_id": survivor}
        await turn_fight.command("declare_phase", {"declarations": [swing]})
        with (
            patch("check_resolution.dice_roll", return_value=_d20(18)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await turn_fight.drain()
        (receipt,) = [p for p in packets if p["actor_id"] == "skeleton" and "hit" in p]
        assert receipt["hit"] and not receipt.get("fled")
        assert (await player_row(survivor))["hp"]["current"] == before - receipt["damage"]
    finally:
        await lifecycle.aclose()


async def test_landed_entomb_on_a_departed_target_keeps_its_receipt(reset_db_pool) -> None:
    from acceptance.test_slippery_restrain import advance, declare

    harness = MawlingHarness()
    try:
        await harness.prepare((5, 5), companion=None, location=WORKS)
        host, guest = harness.players
        await patch_player(guest, **{"class": "rogue"})
        state = await enter(harness)
        assert state.architect_encounter is not None and state.spatial is not None
        owner = state.architect_encounter["owner_id"]
        state.spatial["positions"].update({guest: pos(5), host: pos(40), owner: pos(0)})
        await harness.persist()
        await declare(harness, owner, guest, "Entomb")
        with (
            patch("check_resolution.dice_roll", return_value=_d20(1)),
            patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)),
        ):
            _, window = await advance(harness, expect_condition_window=True)
            assert window is not None and window["target_id"] == guest
            lifecycle = await depart(harness, guest)
            try:
                packets = await harness.drain()
            finally:
                await lifecycle.aclose()
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
            lifecycle = await depart(fight, reactor)
            try:
                packets = (await keep_original(fight, offer))["packets"] if concentration else await fight.drain()
            finally:
                await lifecycle.aclose()
        (hit,) = [p for p in packets if p["actor_id"] == fight.enemies[0] and "damage" in p]
        assert hit["damage"] == (6 if concentration else 19)
        assert not [p for p in packets if p.get("ability_id") == DOUBT]
        assert await player_row(reactor) == reactor_row
        if not concentration:
            assert (await player_row(recipient))["hp"]["current"] == hp - hit["damage"]


@pytest.mark.parametrize("fight", [((20, 20), None)], indirect=True)
async def test_departed_victims_chamber_collapses(fight) -> None:
    guest = fight.players[1]
    owner, _, chamber_id = await seal(fight, guest)
    lifecycle = await depart(fight, guest)
    try:
        state = await fight.reload()
        assert_departed(state, guest)
        chamber = state.get_participant(chamber_id)
        assert chamber is not None and (chamber.is_dead, chamber.hp_current) == (True, 0)
        assert not state.spatial.get("chambers")
        await fight.command("declare_phase", {"declarations": [{"reshape": [], "actor_id": owner, "kind": "defend"}]})
        with patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=4)) as damage:
            packets = await fight.drain()
        damage.assert_not_called()
        assert all(p.get("source_id") != chamber_id for p in packets)
    finally:
        await lifecycle.aclose()


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
        await fight.command("declare_phase", defend_all(state))
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(5)):
            for _ in range(4):
                if offer := (await fight.command("resolve_phase", {})).get("fate_offer"):
                    break
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", roller)
            wrap = (await fight.reload()).wrap_continuation
            assert wrap is not None and (guest in wrap["wrap"]["death_saves_due"]) is fallen
            lifecycle = await depart(fight, guest)
            try:
                result = await (keep_original(fight, offer) if fallen else fight.command("resolve_phase", {}))
                assert result.get("fate_offer") is None
                state = await fight.reload()
                assert (state.round_number, state.wrap_continuation) == (2, None)
                assert_departed(state, guest)
            finally:
                await lifecycle.aclose()


async def test_departure_drops_a_paused_inner_fire(reset_db_pool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        guest = fight.players[1]
        await patch_player(guest, race="draethar")
        fight.sd.member_state(guest).concentration.spell_id = SPELL
        await db_mutations_concentration.update_player_concentration(guest, SPELL, conn=fight.pool)
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(5)):
            receipt = await tool_receipt(fight, guest, "activate", {"id": "draethar_inner_fire"})
            assert json.loads(receipt.output)["fate_offer"]["roller_id"] == guest
            assert (await fight.reload()).inner_fire_continuation is not None
            lifecycle = await depart(fight, guest)
            try:
                await fight.command("declare_phase", defend_all(await fight.reload()))
                await fight.drain()
                assert (await fight.reload()).round_number == 2
            finally:
                await lifecycle.aclose()


async def test_departed_movers_held_opportunity_offer_is_withdrawn(reset_db_pool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        host, guest = fight.players
        foe, lookout = fight.enemies
        state = await fight.reload()
        assert state.spatial is not None
        state.spatial["positions"].update({host: pos(30), guest: pos(0), foe: pos(-5), lookout: pos(-60)})
        await fight.persist()
        await fight.command("declare_phase", {"declarations": [move(guest, 25)]})
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
            paused = await fight.command("resolve_phase", {})
            assert paused["fate_offer"]["roller_id"] == foe
            before = await player_row(guest)
            lifecycle = await depart(fight, guest)
            try:
                packets = await fight.drain()
                assert all(p.get("target_id") != guest for p in packets)
                assert (await player_row(guest))["hp"] == before["hp"]
                state = await fight.reload()
                assert state.round_number == 2
                assert_departed(state, guest)
            finally:
                await lifecycle.aclose()
