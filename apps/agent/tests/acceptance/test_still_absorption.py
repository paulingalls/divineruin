import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.test_still_actions import reveal_and_wake
from acceptance.test_still_anchors import declare, destroy, enter, search_round, strike
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_still_anchors import still as still
from acceptance.test_still_paradise_trap import arrive, command, exploration, player_row
from acceptance.test_still_paradise_trap import paradise as paradise
from livekit.agents import Agent, AgentSession
from sample_fixtures import published_payloads

import db_content_queries
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import resurrection
import still_charm
import still_dwell
from background_process import BackgroundProcess
from check_resolution import D20Roll
from dice import DiceResult
from event_bus import GameEvent
from movement_tools import party_level_warning

HOUR = 120
DAY = 24 * HOUR
ROLL_D20 = D20Roll.roll


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=time.time())
    monkeypatch.setattr(time, "time", lambda: clock.now)
    return clock


@pytest.fixture
def save_faces(monkeypatch):
    rolls = []
    face = SimpleNamespace(value=1)

    def roll(self, _rng=None):
        result = self.evaluate(face.value)
        rolls.append((self.dc, self.modifier, result.total))
        return result

    monkeypatch.setattr(D20Roll, "roll", roll)
    return face, rolls


@pytest.fixture
def losses(monkeypatch):
    faces = iter([4, 1])
    rolls = []

    def roll(notation, _rng=None):
        assert notation == "1d4"
        face = next(faces)
        rolls.append(face)
        return DiceResult(notation, [face], [], face)

    monkeypatch.setattr("dice.roll", roll)
    return rolls


@pytest.fixture(autouse=True)
def speech_transport(monkeypatch):
    speech = AsyncMock(return_value=True)
    monkeypatch.setattr("background_process.deliver_speech", speech)
    return speech


def live_party(walk):
    generations = getattr(walk, "dwell_generations", dict.fromkeys(walk.players, 1))
    walk.sd.multiplayer_owner = SimpleNamespace(
        lifecycle=SimpleNamespace(is_live=generations.__contains__, current_generation=generations.get)
    )


@asynccontextmanager
async def background(walk):
    live_party(walk)
    process = BackgroundProcess(walk.session, walk.sd)
    assert walk.sd.background is None
    walk.sd.background = process
    process._rebuild_warm_layer = AsyncMock(return_value=True)
    process._alignment.maybe_tick = AsyncMock()
    done = asyncio.Event()
    pulse = "test-dwell-pulse"
    seen = False
    handle, deliver = process._handle_events, process._deliver_speech

    def handle_events(events):
        nonlocal seen
        seen = any(event.event_type == pulse for event in events)
        return handle(events)

    async def deliver_speech():
        await deliver()
        if seen:
            done.set()

    async def tick():
        run = process._task
        assert run is not None
        done.clear()
        walk.sd.event_bus.publish(GameEvent(pulse, {}))
        async with asyncio.timeout(5):
            waiter = asyncio.create_task(done.wait())
            try:
                await asyncio.wait((waiter, run), return_when=asyncio.FIRST_COMPLETED)
                if run.done():
                    run.result()
            finally:
                waiter.cancel()

    process._handle_events = handle_events
    process._deliver_speech = deliver_speech
    process.start()
    try:
        await tick()
        yield tick
    finally:
        try:
            await process.stop()
        finally:
            walk.sd.background = None


@asynccontextmanager
async def independent_guest(walk, guest, zone):
    other = SimpleNamespace(sd=type(walk.sd)(player_id=guest, location_id=zone, room=walk.sd.room), players=[guest])
    other.session = AgentSession(llm=walk.model, userdata=other.sd)
    await other.session.start(Agent(instructions="Describe the effects."))
    try:
        async with background(other) as tick:
            yield tick
    finally:
        await other.session.aclose()


async def parked(wait):
    """Park inside an open transaction for at most 5 s, so a lost wake-up fails instead of holding row locks."""
    async with asyncio.timeout(5):
        return await wait


async def advance(clock, tick, seconds):
    while seconds:
        step = min(seconds, HOUR // 2)
        clock.now += step
        seconds -= step
        await tick()


async def charm(pid, zone):
    return still_charm.read(await player_row(pid), pid, zone)


async def set_attributes(walk, pid, **attributes):
    await walk.pool.execute(
        "UPDATE players SET data=jsonb_set(data, '{attributes}', $2::jsonb) WHERE player_id=$1",
        pid,
        json.dumps(attributes),
    )


async def test_hourly_save_resets_on_success_and_reentry(paradise, clock, save_faces):
    walk, origin, zone = paradise
    guest = walk.players[1]
    await arrive(walk, "move_player", zone)
    face, rolls = save_faces
    face.value = 17
    async with background(walk) as tick:
        await advance(clock, tick, HOUR - 1)
        assert not rolls and await charm(guest, zone)
        await advance(clock, tick, 1)
        await tick()
        assert rolls == [(18, 0, 17)]
        assert await charm(guest, zone)
        await advance(clock, tick, HOUR)
        assert rolls == [(18, 0, 17), (18, 1, 18)]
        assert await charm(guest, zone) is None
        assert f"still_dwell:{zone}" not in (await player_row(guest))["flags"]

        async def interposed_tick(*args, **kwargs):
            await tick()
            assert await charm(guest, zone) is None
            return await party_level_warning(*args, **kwargs)

        with patch("travel_tools.party_level_warning", side_effect=interposed_tick):
            assert (await arrive(walk, "travel", origin))["arrived"]
        await arrive(walk, "move_player", zone)
        await advance(clock, tick, HOUR)
        assert rolls[-1] == (18, 0, 17)
        assert len(rolls) == 3 and await charm(guest, zone)


async def test_touch_expires_after_combat(still, clock):
    state = await reveal_and_wake(still)
    pid, zone = still.players[0], state.location_id
    owner = state.still_encounter["owner_id"]
    state.spatial["positions"][pid] = {**state.spatial["positions"][owner], "x": 120}
    await still.persist()
    await declare(still, actor_id=owner, **strike(pid, action="Serenity's Touch"))
    with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1)):
        await still.drain()
    active = await charm(pid, zone)
    assert active is not None and active["kind"] == "serenitys_touch"

    async with background(still) as tick:
        await advance(clock, tick, HOUR + 30)
        assert await charm(pid, zone)
        assert (await still.reload()).still_encounter["owner_id"] == owner
        clock.now += 20
        await still.command("end_combat", {"outcome": "fled"})
        await tick()
        await advance(clock, tick, HOUR - 1)
        assert await charm(pid, zone)
        await advance(clock, tick, 1)
        assert await charm(pid, zone) is None
        result, resumed = await enter(still)
        assert result["still"]["charmed_player_ids"] == []
        assert all(c["source"] != owner for c in resumed.get_participant(pid).conditions)


async def test_short_disconnect_and_restart_resume_from_checkpoint(paradise, clock, save_faces):
    walk, _, zone = paradise
    guest = walk.players[1]
    walk.dwell_generations = dict.fromkeys(walk.players, 1)
    await arrive(walk, "move_player", zone)
    _, rolls = save_faces
    async with background(walk) as tick:
        await advance(clock, tick, HOUR - 2)
        del walk.dwell_generations[guest]
        await advance(clock, tick, 60)
        walk.dwell_generations[guest] = 2
        await tick()
        assert not rolls
        await advance(clock, tick, 1)
    clock.now += 30
    await exploration(walk)
    async with background(walk) as tick:
        assert not rolls
        await advance(clock, tick, 1)
        assert rolls == [(18, 0, 1)]


async def test_stalled_wakeup_counts_no_dwell(paradise, clock, save_faces):
    walk, _, zone = paradise
    guest = walk.players[1]
    await arrive(walk, "move_player", zone)
    _, rolls = save_faces
    async with background(walk) as tick:
        await advance(clock, tick, HOUR - 1)
        before = still_charm.read_clock(await player_row(guest), guest, zone)
        assert before is not None
        clock.now += still_dwell.MAX_COUNTED_GAP_SECS + 1
        await tick()
        after = still_charm.read_clock(await player_row(guest), guest, zone)
        assert after == {**before, "checkpoint_at": clock.now}
        assert not rolls


async def test_daily_drain_concurrent_and_restarted(paradise, clock, save_faces, losses, speech_transport):
    walk, _, zone = paradise
    guest = walk.players[1]
    await set_attributes(walk, guest, strength=14, dexterity=13, wisdom=10)
    await arrive(walk, "move_player", zone)
    _, rolls = save_faces
    async with background(walk) as tick:
        await advance(clock, tick, DAY - 1)
        assert len(rolls) == 23 and not losses
        await enter(walk)
        await advance(clock, tick, HOUR)
        clock.now += 10
        await walk.command("end_combat", {"outcome": "fled"})
        await tick()
        assert len(rolls) == 23 and not losses
        async with independent_guest(walk, guest, zone) as simultaneous:
            barrier = asyncio.Barrier(2)
            connections = set()
            get_player = still_dwell.db_queries.get_player

            async def lock_together(pid, *, for_update=False, conn=None):
                if pid == guest and for_update and len(connections) < 2:
                    connections.add(conn)
                    await parked(barrier.wait())
                return await get_player(pid, for_update=for_update, conn=conn)

            clock.now += 1
            with patch.object(still_dwell.db_queries, "get_player", side_effect=lock_together):
                await asyncio.gather(tick(), simultaneous())
            assert len(connections) == 2
        assert len(rolls) == 24 and losses == [4]
        assert (await player_row(guest))["attributes"] == {"strength": 10, "dexterity": 13, "wisdom": 10}
        assert sum("Iona loses 4 strength" in call.args[1] for call in speech_transport.call_args_list) == 1

    clock.now += DAY
    await exploration(walk)
    async with background(walk) as restarted:
        await restarted()
        assert len(rolls) == 24 and losses == [4]
        await advance(clock, restarted, HOUR // 2)
    await exploration(walk)
    async with background(walk) as restarted:
        await advance(clock, restarted, HOUR // 2)
        assert len(rolls) == 25
        await advance(clock, restarted, DAY - HOUR)
    assert len(rolls) == 48 and losses == [4, 1]
    assert (await player_row(guest))["attributes"] == {"strength": 10, "dexterity": 12, "wisdom": 10}
    assert "Iona loses 1 dexterity" in speech_transport.call_args.args[1]


async def test_interrupted_drain_rolls_back_before_retry(paradise, clock, save_faces, speech_transport):
    walk, _, zone = paradise
    guest = walk.players[1]
    await set_attributes(walk, guest, strength=14, wisdom=10)
    await arrive(walk, "move_player", zone)
    die = DiceResult("1d4", [4], [], 4)
    with patch("dice.roll", return_value=die):
        with pytest.raises(RuntimeError, match="interrupted drain"):
            async with background(walk) as tick:
                await advance(clock, tick, DAY - 1)
                before = await player_row(guest)
                events = list(walk.sd.recent_events)

                async def interrupt(_pid, _zone, _clock, *, mutations, conn):
                    pending = await db_queries.get_player(guest, conn=conn)
                    assert pending is not None and pending["attributes"]["strength"] == 10
                    raise RuntimeError("interrupted drain")

                with patch.object(still_charm, "write_clock", side_effect=interrupt):
                    await advance(clock, tick, 1)
        assert await player_row(guest) == before
        assert list(walk.sd.recent_events) == events
        assert all("Iona loses" not in call.args[1] for call in speech_transport.call_args_list)
        clock.now -= 1
        await exploration(walk)
        async with background(walk) as tick:
            await advance(clock, tick, 1)
            assert (await player_row(guest))["attributes"]["strength"] == 10
            assert "Iona loses 4 strength" in speech_transport.call_args.args[1]


@pytest.mark.parametrize(("index", "score"), [(0, 4), (1, 3)])
async def test_absorption_death_uses_resurrection_once(paradise, clock, save_faces, losses, index, score):
    walk, origin, zone = paradise
    pid = walk.players[index]
    guest = walk.players[1]
    await set_attributes(walk, pid, strength=score, wisdom=2)
    if index == 0:
        await set_attributes(walk, guest, strength=14, wisdom=2)
        walk.dwell_generations = {pid: 1}
        await walk.pool.execute(
            "UPDATE locations SET data=jsonb_set(data, '{navigation}', $2::jsonb) WHERE id=$1",
            origin,
            json.dumps("established_road"),
        )
    await db_mutations.set_player_flag(pid, "unrelated", True)
    await db_mutations_conditions.save_player_conditions(pid, [{"type": "charmed", "source": "unrelated", "stacks": 1}])
    with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(1 if self.modifier < 0 else 20)):
        assert (await command(walk, "move_player", zone))["moved"]
    assert await charm(pid, zone)
    with patch.object(resurrection, "trigger_character_death", wraps=resurrection.trigger_character_death) as death:
        async with background(walk) as tick:
            await advance(clock, tick, DAY)
            assert death.await_count == 1 and losses == [4]
            row = await player_row(pid)
            assert row["attributes"]["strength"] == score - 4
            assert row["death_history"]["count"] == 1
            assert row["location_id"] != zone and row["hp"]["current"] == row["hp"]["max"]
            assert row["flags"]["unrelated"] is True
            assert row["conditions"] == [{"type": "charmed", "source": "unrelated", "stacks": 1}]
            assert not any(flag.startswith(("still_charm:", "still_dwell:")) for flag in row["flags"])
            assert walk.sd.location_id == (row["location_id"] if index == 0 else zone)
            assert any(p["type"] == E.SESSION_INIT for p in published_payloads(walk.sd.room))
            if index == 0:
                guest_before = await player_row(guest)
                assert guest_before["location_id"] == zone and await charm(guest, zone)
                anchor = await db_content_queries.get_location(row["location_id"])
                assert anchor is not None
                destination = next(
                    entry["destination"] for entry in anchor["exits"].values() if not entry.get("requires")
                )
                for verb, target in (("move_player", destination), ("travel", origin)):
                    assert "Iona does not want to leave" in await command(walk, verb, target)
                    assert await player_row(pid) == row
                    assert await player_row(guest) == guest_before
        await exploration(walk)
        async with background(walk) as restarted:
            await advance(clock, restarted, DAY)
        assert death.await_count == 1
        assert await player_row(pid) == row


async def test_combat_resurrection_clears_the_guest_charm(paradise, clock):
    walk, _, zone = paradise
    guest = walk.players[1]
    await arrive(walk, "move_player", zone)
    _, state = await enter(walk)
    participant = state.get_participant(guest)
    participant.hp_current = 0
    participant.is_fallen = participant.is_dead = True
    await walk.persist()
    assert await charm(guest, zone)
    await walk.command("end_combat", {"outcome": "fled"})
    row = await player_row(guest)
    assert row["death_history"]["count"] == 1 and row["location_id"] != zone
    assert await charm(guest, zone) is None and f"still_dwell:{zone}" not in row["flags"]


@pytest.mark.parametrize("cleanup_first", [False, True])
async def test_destroyed_still_stops_dwell_for_guest(paradise, clock, save_faces, losses, cleanup_first):
    walk, _, zone = paradise
    guest = walk.players[1]
    await arrive(walk, "move_player", zone)
    _, rolls = save_faces
    async with background(walk) as tick:
        await advance(clock, tick, DAY)
        assert len(rolls) == 24 and losses == [4]
    with patch.object(D20Roll, "roll", ROLL_D20):
        response, initial = await enter(walk)
        search = response["still"]["search_actions"][0]
        *earlier, last = initial.still_encounter["anchor_ids"]
        for anchor in earlier:
            await search_round(walk, search)
            await destroy(walk, anchor)
        await search_round(walk, search)
    async with independent_guest(walk, guest, zone) as tick:
        await advance(clock, tick, HOUR - 1)
        first_locked = asyncio.Event()
        second_requested = asyncio.Event()
        get_player, get_players = db_queries.get_player, db_queries.get_players_for_update
        clear = still_charm.clear

        async def lock_member(pid, *, for_update=False, conn=None):
            due_tick = pid == guest and for_update
            if due_tick and cleanup_first:
                second_requested.set()
            row = await get_player(pid, for_update=for_update, conn=conn)
            if due_tick and not cleanup_first:
                first_locked.set()
                await parked(second_requested.wait())
            return row

        async def clear_after_lock(*args, **kwargs):
            if cleanup_first:
                first_locked.set()
                await parked(second_requested.wait())
            return await clear(*args, **kwargs)

        async def lock_party(*args, **kwargs):
            if not cleanup_first:
                second_requested.set()
            return await get_players(*args, **kwargs)

        track_dwell = D20Roll.roll

        def roll_during_race(roll, rng=None):
            return track_dwell(roll, rng) if roll.dc == 18 else ROLL_D20(roll, rng)

        clock.now += 1
        with (
            patch.object(D20Roll, "roll", roll_during_race),
            patch.object(db_queries, "get_player", side_effect=lock_member),
            patch.object(still_charm, "clear", side_effect=clear_after_lock),
            patch.object(db_queries, "get_players_for_update", side_effect=lock_party),
        ):
            async with asyncio.timeout(5), asyncio.TaskGroup() as race:
                race.create_task(destroy(walk, last) if cleanup_first else tick())
                await first_locked.wait()
                race.create_task(tick() if cleanup_first else destroy(walk, last))

        expected_saves = 24 if cleanup_first else 25
        assert len(rolls) == expected_saves and losses == [4]
        assert walk.last_result["still"]["charmed_player_ids"] == []
        before = await player_row(guest)
        assert still_charm.read(before, guest, zone) is None
        assert f"still_dwell:{zone}" not in before["flags"]
        await advance(clock, tick, DAY)
        assert await player_row(guest) == before
        assert len(rolls) == expected_saves and losses == [4]
