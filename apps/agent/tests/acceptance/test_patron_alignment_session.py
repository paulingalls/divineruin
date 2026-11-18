"""Patron judgments through the running CLI session and persisted combat deeds."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
import pytest
from acceptance.first_episode_harness import episode, until
from acceptance.rider_reentry_walk import saved_rider
from acceptance.rider_walk import requested

import alignment_heartbeat
import background_process
import db
import db_mutations
import db_queries
import event_types as E
from event_bus import GameEvent


@pytest.fixture
def mock_combat_agent_factory():
    yield


@pytest.fixture
def stub_companion_hydrate_io():
    yield


async def prepared(pid):
    await saved_rider(pid)
    await db_mutations.set_player_flag(pid, "first_episode", "complete")
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,level}', '50'::jsonb) WHERE player_id=$1", pid
    )


async def produce(run, outcome="victory"):
    receipt = await run.turn("enter_mode", mode="combat", encounter_id="fragment_shadeling")
    assert not receipt.is_error, receipt.output
    await until(lambda: run.session.current_agent.__class__.__name__ == "CombatAgent")
    cs = run.session.userdata.combat_state
    assert cs is not None
    if outcome == "victory":
        for actor in cs.participants:
            if actor.type == "enemy":
                actor.hp_current = 0
                actor.is_fallen = True
        await db_mutations.save_combat_state(cs.combat_id, cs.to_dict())
    receipt = await run.turn("end_combat", outcome=outcome)
    assert not receipt.is_error, receipt.output
    await until(lambda: run.session.current_agent.__class__.__name__ == "ExplorationAgent")


class LoopClock:
    def __init__(self, monkeypatch):
        self.value = 10000.0
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(
            background_process,
            "AlignmentHeartbeat",
            lambda sd: alignment_heartbeat.AlignmentHeartbeat(sd, now=lambda: self.value),
        )

    async def attach(self, run):
        self.origin = self.value
        self.sd = run.session.userdata
        self.marker = self.completed = self.held = None
        self.seen = False
        get, drain = self.sd.event_bus.get, self.sd.event_bus.drain
        entered = asyncio.Event()

        async def observed_get(**kwargs):
            entered.set()
            if self.seen:
                self.seen = False
                self.held = asyncio.get_running_loop().create_future()
                assert self.completed is not None
                self.completed.set_result(None)
                await self.held
            event = await get(**kwargs)
            if self.marker is not None and event is self.marker:
                self.seen = True
            return event

        def observed_drain():
            events = drain()
            if self.marker is not None and any(event is self.marker for event in events):
                self.seen = True
            return events

        self.monkeypatch.setattr(self.sd.event_bus, "get", observed_get)
        self.monkeypatch.setattr(self.sd.event_bus, "drain", observed_drain)
        # The loop can already be awaiting the original get when this observer attaches.
        self.sd.event_bus.publish(GameEvent(E.DICE_ROLL, {}))
        await asyncio.wait_for(entered.wait(), 25)
        await until(lambda: self.sd.primary_player_id in self.sd.present_member_ids)

    async def tick(self, elapsed):
        self.value = self.origin + elapsed
        self.marker = GameEvent(E.DICE_ROLL, {})
        self.completed = asyncio.get_running_loop().create_future()
        if self.held is not None:
            self.held.set_result(None)
            self.held = None
        self.sd.event_bus.publish(self.marker)
        await asyncio.wait_for(asyncio.shield(self.completed), 25)


async def state(pid):
    player = await db_queries.get_player(pid)
    assert player is not None
    return player["divine_favor"]["level"], player.get("patron_deeds", {})


@pytest.fixture
def clock(monkeypatch):
    return LoopClock(monkeypatch)


@pytest.fixture
def published(monkeypatch):
    observations = []
    publish = alignment_heartbeat.publish_game_event

    async def observed(room, kind, payload, **kwargs):
        observations.append((payload, await state(payload["player_id"])))
        await publish(room, kind, payload, **kwargs)

    monkeypatch.setattr(alignment_heartbeat, "publish_game_event", observed)
    return observations


async def test_due_once_and_recent_context(livekit_server, reset_db_pool, tmp_path, clock, published):
    async with episode(livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        await produce(run)
        assert await state(run.player_id) == (50, {"won_combat": "pending"})
        await clock.tick(1199)
        assert await state(run.player_id) == (50, {"won_combat": "pending"})
        await clock.tick(1200)
        assert await state(run.player_id) == (52, {})
        await until(lambda: len(run.packets(E.DIVINE_FAVOR_CHANGED)) == 1)
        assert len(published) == 1 and published[0][1] == (52, {})
        packet = run.packets(E.DIVINE_FAVOR_CHANGED)[0]
        assert (packet["player_id"], packet["amount"], packet["patron_id"]) == (run.player_id, 2, "kaelen")
        memory = next(line for line in clock.sd.recent_events if "Patron deed judgment" in line)
        assert all(text in memory for text in (run.player_id, "kaelen", "+2", "52"))
        await clock.tick(1200)
        await until(lambda: run.session.current_speech is None and not clock.sd.background._speech_queue)
        receipt = await run.turn("query_info", kind="location", target_id=clock.sd.location_id)
        assert not receipt.is_error, receipt.output
        assert requested(run, memory)
        await clock.tick(2400)
        assert await state(run.player_id) == (52, {})
        assert len(run.packets(E.DIVINE_FAVOR_CHANGED)) == 1
        assert [line for line in clock.sd.recent_events if "Patron deed judgment" in line] == [memory]
        await produce(run, "fled")
        assert await state(run.player_id) == (52, {"fled_combat": "pending"})
        await clock.tick(3599)
        assert await state(run.player_id) == (52, {"fled_combat": "pending"})
        assert len(published) == 1
        await clock.tick(3600)
        assert await state(run.player_id) == (49, {})
        assert len(published) == 2 and published[1][1] == (49, {})
        await until(lambda: len(run.packets(E.DIVINE_FAVOR_CHANGED)) == 2)
        packet = run.packets(E.DIVINE_FAVOR_CHANGED)[1]
        assert (packet["player_id"], packet["amount"], packet["patron_id"]) == (run.player_id, -3, "kaelen")
        judgments = [line for line in clock.sd.recent_events if "Patron deed judgment" in line]
        assert len(judgments) == 2 and judgments[0] == memory
        assert all(text in judgments[1] for text in (run.player_id, "kaelen", "-3", "49"))


async def test_pause_then_negative_judgment(livekit_server, reset_db_pool, tmp_path, clock, published):
    async with episode(livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        await produce(run, "fled")
        clock.sd.background.pause()
        await clock.tick(1200)
        assert await state(run.player_id) == (50, {"fled_combat": "pending"})
        assert published == []
        clock.sd.background.resume()
        await clock.tick(1200)
        assert await state(run.player_id) == (47, {})
        assert len(published) == 1 and published[0][1] == (47, {})
        assert published[0][0]["amount"] == -3
        assert any(run.player_id in line and "kaelen" in line and "-3 to 47" in line for line in clock.sd.recent_events)
        await until(lambda: len(run.packets(E.DIVINE_FAVOR_CHANGED)) == 1)


async def test_transient_rollback_retries(
    livekit_server, reset_db_pool, tmp_path, clock, published, monkeypatch, caplog
):
    judge = alignment_heartbeat.judge_pending_deeds
    failed = False

    async def fail_once(*args, **kwargs):
        nonlocal failed
        result = await judge(*args, **kwargs)
        if not failed:
            failed = True
            raise asyncpg.PostgresError("injected transaction failure")
        return result

    monkeypatch.setattr(alignment_heartbeat, "judge_pending_deeds", fail_once)
    async with episode(livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        await produce(run)
        await clock.tick(1200)
        assert failed and not clock.sd.background._task.done()
        assert "injected transaction failure" in caplog.text
        assert await state(run.player_id) == (50, {"won_combat": "pending"})
        assert published == []
        assert not any("Patron deed judgment" in line for line in clock.sd.recent_events)
        await clock.tick(1200)
        assert await state(run.player_id) == (52, {})
        assert len(published) == 1


async def test_programmer_error_ends_background(
    livekit_server, reset_db_pool, tmp_path, clock, published, monkeypatch, caplog
):
    error = TypeError("injected programmer error")

    async def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(alignment_heartbeat, "judge_pending_deeds", broken)
    async with episode(livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        await produce(run)
        clock.value += 1200
        clock.sd.event_bus.publish(GameEvent(E.DICE_ROLL, {}))
        with pytest.raises(TypeError) as raised:
            await asyncio.wait_for(asyncio.shield(clock.sd.background._task), 5)
        assert raised.value is error
        await until(lambda: "Background process failed" in caplog.text)
        assert await state(run.player_id) == (50, {"won_combat": "pending"})
        assert published == []
        assert not any("Patron deed judgment" in line for line in clock.sd.recent_events)


async def patron(pid, name):
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', $2::jsonb) WHERE player_id=$1",
        pid,
        json.dumps(name),
    )


async def test_reentry_uses_persisted_patron(livekit_server, reset_db_pool, tmp_path, clock, published):
    async def veythar(pid):
        await prepared(pid)
        await patron(pid, "veythar")

    async with episode(
        livekit_server, tmp_path, prepare=veythar, initial_agent="ExplorationAgent", preserve=True
    ) as run:
        await clock.attach(run)
        pid = run.player_id
        old = clock.sd.background._alignment
        await produce(run)
        assert await state(pid) == (50, {"won_combat": "pending"})
    await patron(pid, "kaelen")
    clock.value = 20000
    async with episode(livekit_server, tmp_path, player_id=pid, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        assert clock.sd.background._alignment is not old
        await clock.tick(1199)
        assert await state(pid) == (50, {"won_combat": "pending"})
        await clock.tick(1200)
        assert await state(pid) == (52, {})
        await clock.tick(2400)
        assert await state(pid) == (52, {})
        assert len(published) == 1


async def test_publication_failure_keeps_committed_judgment(
    livekit_server, reset_db_pool, tmp_path, clock, monkeypatch
):
    error = OSError("injected publication failure")
    observed = []

    async def broken(room, kind, payload, **kwargs):
        observed.append(await state(payload["player_id"]))
        raise error

    with monkeypatch.context() as transport:
        transport.setattr(alignment_heartbeat, "publish_game_event", broken)
        async with episode(
            livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent", preserve=True
        ) as run:
            await clock.attach(run)
            pid = run.player_id
            await produce(run)
            clock.value += 1200
            clock.sd.event_bus.publish(GameEvent(E.DICE_ROLL, {}))
            with pytest.raises(OSError) as raised:
                await asyncio.wait_for(asyncio.shield(clock.sd.background._task), 5)
            assert raised.value is error
            assert observed == [(52, {})]
            assert clock.sd.background._alignment._last_tick == clock.value
            assert any("Patron deed judgment" in line for line in clock.sd.recent_events)
    clock.value = 30000
    async with episode(livekit_server, tmp_path, player_id=pid, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        await clock.tick(1200)
        assert await state(pid) == (52, {})
        assert run.packets(E.DIVINE_FAVOR_CHANGED) == []
        assert not any("Patron deed judgment" in line for line in clock.sd.recent_events)


@pytest.fixture(autouse=True)
def local_room_admin(livekit_server, monkeypatch):
    for name, value in (
        ("LIVEKIT_URL", livekit_server["ws_url"]),
        ("LIVEKIT_API_KEY", livekit_server["api_key"]),
        ("LIVEKIT_API_SECRET", livekit_server["api_secret"]),
    ):
        monkeypatch.setenv(name, value)


@pytest.fixture
async def members():
    ids = []

    async def create(patron_id="kaelen"):
        pid = f"alignment-{uuid4().hex}"
        ids.append(pid)
        await prepared(pid)
        await patron(pid, patron_id)
        return pid

    yield create
    pool = await db.get_pool()
    for pid in ids:
        await pool.execute("DELETE FROM companion_relationships WHERE player_id=$1", pid)
        await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def test_guest_patron_and_journals(livekit_server, reset_db_pool, tmp_path, clock, published, members):
    async def veythar(pid):
        await prepared(pid)
        await patron(pid, "veythar")

    async with episode(livekit_server, tmp_path, prepare=veythar, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        guest = await members()
        _, packets = await run.connect_member(guest)
        await produce(run)
        assert await state(run.player_id) == await state(guest) == (50, {"won_combat": "pending"})
        await clock.tick(1200)
        assert await state(run.player_id) == (50, {})
        assert await state(guest) == (52, {})
        assert len(published) == 1 and published[0][0]["player_id"] == guest
        await until(lambda: any(p["type"] == E.DIVINE_FAVOR_CHANGED and p["player_id"] == guest for p, _ in packets))
        lines = [line for line in clock.sd.recent_events if "Patron deed judgment" in line]
        assert len(lines) == 1 and guest in lines[0] and run.player_id not in lines[0]


async def test_handoff_keeps_clock_and_excludes_departed(
    livekit_server, reset_db_pool, tmp_path, clock, published, members
):
    from acceptance._livekit_client import aclose_room

    async with episode(livekit_server, tmp_path, prepare=prepared, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        background = clock.sd.background
        heartbeat = background._alignment
        successor, absent = await members(), await members()
        _, packets = await run.connect_member(successor)
        absent_room, _ = await run.connect_member(absent)
        await produce(run)
        for pid in (run.player_id, successor, absent):
            assert await state(pid) == (50, {"won_combat": "pending"})
        await aclose_room(absent_room)
        await until(lambda: absent not in clock.sd.present_member_ids)
        assert absent in clock.sd.party.member_ids
        await clock.tick(1199)
        receipt = await run.turn("end_session", reason="I must leave")
        assert not receipt.is_error, receipt.output
        await until(lambda: clock.sd.departure_task is not None)
        await asyncio.wait_for(asyncio.shield(clock.sd.departure_task), 25)
        assert clock.sd.primary_player_id == successor
        assert clock.sd.background is background and background._alignment is heartbeat
        await clock.tick(1200)
        assert await state(successor) == (52, {})
        for pid in (run.player_id, absent):
            assert await state(pid) == (50, {"won_combat": "pending"})
        assert len(published) == 1 and published[0][0]["player_id"] == successor
        await until(
            lambda: any(p["type"] == E.DIVINE_FAVOR_CHANGED and p["player_id"] == successor for p, _ in packets)
        )
        await clock.tick(2400)
        assert await state(successor) == (52, {})
        assert len(published) == 1


async def test_unbound_autonomy_memory_after_commit(
    livekit_server, reset_db_pool, tmp_path, clock, monkeypatch, caplog
):
    async def prepare(pid):
        await prepared(pid)
        pool = await db.get_pool()
        await pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            pid,
            json.dumps(
                {
                    "divine_favor": {"patron": "none", "level": 0, "max": 100},
                    "unbound_autonomy": {"level": 38, "max": 100, "tier": "Self-Reliant"},
                }
            ),
        )

    transaction = db.transaction

    @asynccontextmanager
    async def fail_before_commit():
        async with transaction() as conn:
            yield conn
            raise asyncpg.PostgresError("autonomy pre-commit failure")

    async with episode(livekit_server, tmp_path, prepare=prepare, initial_agent="ExplorationAgent") as run:
        await clock.attach(run)
        clock.sd.companion = None
        await produce(run)
        before = await db_queries.get_player(run.player_id)
        assert before is not None
        assert before["patron_deeds"] == {"won_combat": "pending", "won_alone": "pending"}
        await clock.tick(1199)
        assert await db_queries.get_player(run.player_id) == before
        with monkeypatch.context() as fault:
            fault.setattr(db, "transaction", fail_before_commit)
            await clock.tick(1200)
        assert "autonomy pre-commit failure" in caplog.text
        assert await db_queries.get_player(run.player_id) == before
        assert not any("Autonomy" in line for line in clock.sd.recent_events)
        await clock.tick(1200)
        after = await db_queries.get_player(run.player_id)
        assert after is not None
        assert after["unbound_autonomy"] == {"level": 42, "max": 100, "tier": "Self-Forged"}
        assert after["patron_deeds"] == {}
        memory = next(line for line in clock.sd.recent_events if "Autonomy" in line)
        assert all(text in memory for text in (run.player_id, "+4", "42", "Self-Forged"))
        await until(lambda: run.session.current_speech is None and not clock.sd.background._speech_queue)
        receipt = await run.turn("query_info", kind="location", target_id=clock.sd.location_id)
        assert not receipt.is_error, receipt.output
        assert requested(run, memory)
        await clock.tick(2400)
        repeated = await db_queries.get_player(run.player_id)
        assert repeated is not None and repeated["unbound_autonomy"] == after["unbound_autonomy"]
        assert [line for line in clock.sd.recent_events if "Autonomy" in line] == [memory]
        assert not run.packets(E.DIVINE_FAVOR_CHANGED)
