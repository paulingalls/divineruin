import asyncio
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party

import db_mutations
import patron_gift_tools
from activate_tools import activate
from check_tools import check
from combat_turn import declare_phase, resolve_phase
from session_data import SessionData

FATE = "zhael_fates_thread"
SAVE = {"kind": "save", "save_type": "wisdom", "dc": 15, "effect_on_fail": "frightened"}


async def test_two_eligible_followers_race_for_one_offer(world):
    for index in range(2):
        await configure(world, "zhael", "mage", index=index)
    session = world.ctx.userdata
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, check, activate)
    start = asyncio.Event()

    async def respond(player_id, offer_id, **extra):
        await start.wait()
        with session._bind_authenticated_actor(player_id, 1, lifecycle.require_authorized):
            return await call("activate", id=FATE, offer_id=offer_id, **extra)

    try:
        with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]) as dice:
            offer = (await call("check", roll=SAVE))["fate_offer"]
            assert offer["eligible_followers"] == world.ids
            attempts = [asyncio.create_task(respond(pid, offer["offer_id"])) for pid in world.ids]
            start.set()
            results = await asyncio.gather(*attempts, return_exceptions=True)
            winner = next(i for i, result in enumerate(results) if isinstance(result, dict))
            loser = 1 - winner
            assert isinstance(results[loser], ToolError) and world.ids[winner] in str(results[loser])
            assert dice.call_count == 2
        assert (await row(world, winner))["patron_gifts"][FATE] == {"spent": True}
        assert FATE not in (await row(world, loser)).get("patron_gifts", {})
        with pytest.raises(ToolError, match=world.ids[winner]):
            await respond(world.ids[loser], offer["offer_id"], keep="reroll")
        assert (await respond(world.ids[winner], offer["offer_id"], keep="reroll"))["outcome"] == "success"
    finally:
        await lifecycle.aclose()


async def test_two_sessions_serialize_spend_on_the_player_row(world):
    pid = world.ids[0]
    await configure(world, "zhael", "mage")
    sessions = [world.ctx.userdata, SessionData(player_id=pid, location_id="accord_guild_hall")]
    calls = [game_tools(session, check, activate) for session in sessions]
    with patch("check_resolution.dice_roll", side_effect=[_d20(2), _d20(3), _d20(20)]) as dice:
        offers = [(await call("check", roll=SAVE))["fate_offer"] for call in calls]
        results = await asyncio.gather(
            *(call("activate", id=FATE, offer_id=offer["offer_id"]) for call, offer in zip(calls, offers, strict=True)),
            return_exceptions=True,
        )
        loser = next(i for i, result in enumerate(results) if isinstance(result, ToolError))
        assert "spent" in str(results[loser])
        result = results[1 - loser]
        assert isinstance(result, dict) and result["reroll"]["die"] == 20
        assert dice.call_count == 3
    original = await calls[loser]("activate", id=FATE, offer_id=offers[loser]["offer_id"], keep="original")
    assert original["roll"] == offers[loser]["die"] and original["effect_applied"] == "frightened"
    assert (await row(world, 0))["patron_gifts"][FATE] == {"spent": True}


async def test_transaction_abort_preserves_offer_and_attack_checkpoint(world):
    await configure(world, "zhael", "mage")
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    write_state, save_combat_state = patron_gift_tools.write_state, db_mutations.save_combat_state

    async def abort_spend(*args, conn, **kwargs):
        await write_state(*args, conn=conn, **kwargs)
        await conn.execute("SELECT 1 / 0")

    async def abort_impact(*args, conn, **kwargs):
        await save_combat_state(*args, conn=conn, **kwargs)
        await conn.execute("SELECT 1 / 0")

    try:
        await call("declare_phase", declarations=[attack(pid, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(19), _d20(20)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            accept = {"id": FATE, "offer_id": offer["offer_id"]}
            checkpoint = session.combat_state.to_dict()
            with patch("patron_gift_tools.write_state", abort_spend), pytest.raises(asyncpg.DivisionByZeroError):
                await call("activate", **accept)
            assert FATE not in (await row(world, 0)).get("patron_gifts", {})
            shown = await call("activate", **accept)
            assert shown["reroll"]["die"] == 20
            with patch("db_mutations.save_combat_state", abort_impact), pytest.raises(asyncpg.DivisionByZeroError):
                await call("activate", **accept, keep="reroll")
            assert session.combat_state.to_dict() == checkpoint
            saved = await db_mutations.load_combat_state(state.combat_id)
            assert saved is not None and saved.to_dict() == checkpoint
            assert (await row(world, 0))["patron_gifts"][FATE] == {"spent": True}
            kept = await call("activate", **accept, keep="reroll")
            assert kept["packets"][0]["damage"] == 8 and dice.call_count == 3
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(saved, "foe").hp_current == 22
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def test_accept_rechecks_speaker_after_waiting_for_row(world):
    from db_queries import get_player

    await configure(world, "zhael", "mage")
    session = world.ctx.userdata
    pid = world.ids[0]
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, check, activate)

    async def read_and_revoke(*args, **kwargs):
        player = await get_player(*args, **kwargs)
        lifecycle.mark_departed(pid)
        return player

    try:
        with patch("check_resolution.dice_roll", return_value=_d20(2)) as dice:
            offer = (await call("check", roll=SAVE))["fate_offer"]
            with (
                session._bind_authenticated_actor(pid, 1, lifecycle.require_authorized),
                patch("db_queries.get_player", read_and_revoke),
                pytest.raises(ToolError, match="stale"),
            ):
                await call("activate", id=FATE, offer_id=offer["offer_id"])
            assert dice.call_count == 1
        assert FATE not in (await row(world, 0)).get("patron_gifts", {})
    finally:
        await lifecycle.aclose()
