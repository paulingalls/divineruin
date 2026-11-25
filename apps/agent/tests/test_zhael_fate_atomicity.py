import asyncio
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from test_aelora_gift import _live_party
from voice_condition_fixtures import place_actors

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
        assert (await row(world, winner))["patron_gifts"][FATE] == {"uses_spent": 1}
        assert FATE not in (await row(world, loser)).get("patron_gifts", {})
        with pytest.raises(ToolError, match=world.ids[winner]):
            await respond(world.ids[loser], offer["offer_id"], keep="reroll")
        assert (await respond(world.ids[winner], offer["offer_id"], keep="reroll"))["outcome"] == "success"
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("archetype,spent", [("mage", 0), ("oracle", 1)])
async def test_two_sessions_serialize_spend_on_the_player_row(world, archetype, spent):
    pid = world.ids[0]
    await configure(world, "zhael", archetype, patron_gifts={FATE: {"uses_spent": spent}} if spent else {})
    sessions = [world.ctx.userdata, SessionData(player_id=pid, location_id="accord_guild_hall")]
    calls = [game_tools(session, check, activate) for session in sessions]
    tasks = []
    with patch("check_resolution.dice_roll", side_effect=[_d20(2), _d20(3), _d20(20), _d20(20)]) as dice:
        offers = [(await call("check", roll=SAVE))["fate_offer"] for call in calls]
        choices = [{"id": FATE, "offer_id": offer["offer_id"]} for offer in offers]
        try:
            async with world.pool.acquire() as writer, writer.transaction():
                await writer.fetchrow("SELECT * FROM players WHERE player_id=$1 FOR UPDATE", pid)
                backend = await writer.fetchval("SELECT pg_backend_pid()")
                tasks = [
                    asyncio.create_task(call("activate", **choice)) for call, choice in zip(calls, choices, strict=True)
                ]
                async with asyncio.timeout(5):
                    while (
                        await world.pool.fetchval(
                            """WITH RECURSIVE blocked(pid) AS (
                                SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))
                                UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b
                                ON b.pid=ANY(pg_blocking_pids(a.pid))) SELECT count(*) FROM blocked""",
                            backend,
                        )
                        < 2
                    ):
                        assert not any(task.done() for task in tasks)
                        await asyncio.sleep(0.01)
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        refusals = [index for index, result in enumerate(results) if isinstance(result, ToolError)]
        assert len(refusals) == 1 and "unavailable or spent" in str(results[refusals[0]]), results
        loser = refusals[0]
        result = results[1 - loser]
        assert isinstance(result, dict) and result["reroll"]["die"] == 20 and result["remaining_uses"] == 0
        assert dice.call_count == 3
    expected = {"uses_spent": spent + 1}
    assert (await row(world, 0))["patron_gifts"][FATE] == expected
    original = await calls[loser]("activate", **choices[loser], keep="original")
    assert original["roll"] == offers[loser]["die"] and original["effect_applied"] == "frightened"
    assert (await row(world, 0))["patron_gifts"][FATE] == expected


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
            assert (await row(world, 0))["patron_gifts"][FATE] == {"uses_spent": 1}
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


async def test_concentration_settlement_retries_without_replaying_committed_damage(world):
    from acceptance._capstone_helpers import _player
    from sample_fixtures import published_payloads
    from voice_condition_fixtures import place_actors

    from conditions import apply_condition, has_condition
    from db_mutations_concentration import update_player_concentration

    host, victim = world.ids
    await configure(world, "zhael", "mage")
    await configure(world, "aelora", "mage", index=1, hp={"current": 100, "max": 100})
    state = _build_state(host, host, [_enemy("foe", 30)])
    state.participants.append(_player(victim))
    state.initiative_order.insert(1, victim)
    required_player(state, victim).conditions = apply_condition([], "blessed", source="divine_bless")
    place_actors(state)
    session = world.ctx.userdata
    session.combat_state = state
    caster = session.member_state(victim)
    caster.concentration.spell_id = "divine_bless"
    await update_player_concentration(victim, "divine_bless")
    lifecycle = _live_party(session, host, victim)
    call = game_tools(session, declare_phase, resolve_phase, activate)
    save_combat_state = db_mutations.save_combat_state

    async def abort_after_write(*args, conn, **kwargs):
        await save_combat_state(*args, conn=conn, **kwargs)
        await conn.execute("SELECT 1 / 0")

    def keep(offer):
        return call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")

    try:
        await call(
            "declare_phase",
            declarations=[
                defend(host),
                defend(victim),
                {**attack("foe", victim), "action": "Scimitar"},
            ],
        )
        await call("resolve_phase")
        with (
            session._bind_authenticated_actor(host, 1, lifecycle.require_authorized),
            patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(7)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            attack_offer = (await call("resolve_phase"))["fate_offer"]
            save_offer = (await keep(attack_offer))["fate_offer"]
            assert save_offer["roller_id"] == victim and save_offer["die"] == 7
            before = session.combat_state.to_dict()
            published = published_payloads(session.room)
            assert (await row(world))["hp"]["current"] == 96
            with patch("db_mutations.save_combat_state", abort_after_write), pytest.raises(asyncpg.DivisionByZeroError):
                await keep(save_offer)
            saved = await db_mutations.load_combat_state(state.combat_id)
            assert saved is not None and saved.to_dict() == session.combat_state.to_dict() == before
            assert caster.concentration.spell_id == "divine_bless"
            assert published_payloads(session.room) == published
            with patch("combat_events.publish_game_event", side_effect=RuntimeError("publication fault")) as publish:
                settled = await keep(save_offer)
            assert publish.called
            assert settled["packets"][0]["concentration_broken"] == "divine_bless"
            assert dice.call_count == 2 and damage.call_count == 1
            with pytest.raises(ToolError, match="current Fate"):
                await keep(save_offer)
        persisted = await db_mutations.load_combat_state(state.combat_id)
        target = required_player(persisted, victim)
        assert target.hp_current == 96 and not has_condition(target.conditions, "blessed")
        assert (await row(world))["hp"]["current"] == 96
        assert session.member_state(victim).concentration.spell_id is None
    finally:
        await lifecycle.aclose()
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize("reload", [False, True])
async def test_departed_attack_roller_cancels(world, reload):
    host, guest = world.ids
    await configure(world, "zhael", "mage")
    await configure(world, "aelora", "mage", index=1)
    sd = world.ctx.userdata
    state = _build_state(uuid4().hex, host, [_enemy("foe", 30)])
    state.participants.append(_player(guest))
    state.initiative_order.insert(1, guest)
    place_actors(state)
    sd.combat_state = state
    lifecycle = _live_party(sd, host, guest)
    call = game_tools(sd, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[defend(host), attack(guest, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(19)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            offer = (await call("resolve_phase"))["fate_offer"]
            assert offer["roller_id"] == guest
            lifecycle.mark_departed(guest)
            if reload:
                sd.fate_offer = None
                sd.combat_state = await db_mutations.load_combat_state(state.combat_id)
                settled = await call("resolve_phase")
            else:
                with sd._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                    settled = await call(
                        "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                    )
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(saved, "foe").hp_current == 30
        assert any(p.get("outcome") == "cancelled" and "present" in p["reason"] for p in settled["packets"])
        assert saved is not None and saved.ally_continuation is None
        assert sd.fate_offer is None
        await call("resolve_phase")
        saved = await db_mutations.load_combat_state(state.combat_id)
        assert required_player(saved, "foe").hp_current == 30
    finally:
        await lifecycle.aclose()
        await db_mutations.delete_combat_state(state.combat_id)
