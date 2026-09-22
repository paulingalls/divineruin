"""Live-loop exception policy tests for BackgroundProcess."""

import asyncio
import logging
from contextlib import ExitStack, contextmanager
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from livekit.agents import Agent, AgentSession
from livekit.agents.voice.agent_activity import AgentActivity
from speech_handles import completed_handle

import event_types as E
from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from event_bus import GameEvent
from session_data import SessionData

TIMEOUT = 2
BACKGROUND_LOGGER = "divineruin.background"
REAL_SLEEP = asyncio.sleep


async def _skip_delay(_delay):
    await REAL_SLEEP(0)


def _make_process(agent=None):
    sd = SessionData(player_id="player-1", location_id="accord_guild_hall")
    target = agent or MagicMock()
    if agent is None:
        target.static_prompt.return_value = "STATIC"
        target.update_instructions = AsyncMock()
    session = MagicMock()
    session.current_agent = target
    session.generate_reply = MagicMock(side_effect=lambda **_kwargs: completed_handle())
    return BackgroundProcess(session, sd), sd, target


@contextmanager
def _background_data():
    builds = count(1)

    async def build(*_args, **_kwargs):
        return f"warm-{next(builds)}"

    mocks = SimpleNamespace()
    with ExitStack() as stack:
        mocks.rider = stack.enter_context(
            patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None)
        )
        mocks.quests = stack.enter_context(
            patch("background_process.db_queries.get_active_player_quests", new_callable=AsyncMock, return_value=[])
        )
        mocks.location = stack.enter_context(
            patch(
                "background_process.db_content_queries.get_location",
                new_callable=AsyncMock,
                return_value={"name": "Guild Hall"},
            )
        )
        mocks.npcs = stack.enter_context(
            patch("background_process.db_queries.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
        )
        mocks.training = stack.enter_context(
            patch(
                "background_process.db_training.get_player_active_training_activities",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        mocks.build = stack.enter_context(
            patch("background_process.build_warm_layer", new_callable=AsyncMock, side_effect=build)
        )
        yield mocks


def _publish_rebuild(sd):
    sd.event_bus.publish(GameEvent(event_type=E.QUEST_UPDATED, payload={"quest_name": "Changed"}))


def _delivery_data(process):
    process._rebuild_warm_layer = AsyncMock()
    return patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None)


def _start_delivery(process, sd, speech):
    waiting_for_next_event = asyncio.Event()
    bus_get_calls = 0
    real_get = sd.event_bus.get

    async def get_event(timeout=30.0):
        nonlocal bus_get_calls
        bus_get_calls += 1
        if bus_get_calls == 2:
            waiting_for_next_event.set()
        return await real_get(timeout)

    sd.event_bus.get = get_event
    process._speech_queue.append(speech)
    sd.event_bus.publish(GameEvent(event_type=E.DICE_ROLL, payload={}))
    process.start()
    return waiting_for_next_event


def _warning_records(caplog):
    return [r for r in caplog.records if r.name == BACKGROUND_LOGGER and r.levelno == logging.WARNING]


async def _wait(event):
    await asyncio.wait_for(event.wait(), timeout=TIMEOUT)


async def _failed(task, exception_type):
    with pytest.raises(exception_type) as raised:
        await asyncio.wait_for(task, timeout=TIMEOUT)
    await asyncio.sleep(0)
    return raised.value


async def _finish(process):
    task = process._task
    if task is None:
        return
    if not task.done():
        await process.stop()
        return
    try:
        await task
    except BaseException:
        pass


def _assert_failure_record(caplog, exception):
    records = [
        record for record in caplog.records if record.name == BACKGROUND_LOGGER and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    assert records[0].message == "Background process failed"
    assert records[0].exc_info is not None
    assert records[0].exc_info[1] is exception


@pytest.mark.asyncio
async def test_stinger_publish_typeerror_ends_loop_and_logs(caplog):
    process, sd, _ = _make_process()
    failure = TypeError("stinger broke")
    speech = PendingSpeech(SpeechPriority.CRITICAL, "divine cue", stinger_sound="stinger")
    with (
        _delivery_data(process),
        patch("game_events.publish_game_event", new_callable=AsyncMock, side_effect=failure) as publish,
        caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER),
    ):
        _start_delivery(process, sd, speech)
        try:
            exception = await _failed(process._task, TypeError)
            assert exception is failure
            publish.assert_awaited_once()
            process._session.generate_reply.assert_not_called()  # type: ignore[attr-defined]
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_post_delivery_cue_keyerror_ends_loop_and_logs(caplog):
    process, sd, _ = _make_process()
    sd.companion = MagicMock(last_speech_time=0)
    failure = KeyError("cue broke")
    speech = PendingSpeech(SpeechPriority.IMPORTANT, "companion cue")
    with (
        _delivery_data(process),
        patch("background_process.is_companion_cue", side_effect=[False, failure]) as cue_check,
        caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER),
    ):
        _start_delivery(process, sd, speech)
        try:
            exception = await _failed(process._task, KeyError)
            assert exception is failure
            assert cue_check.call_count == 2
            process._session.generate_reply.assert_called_once_with(instructions="companion cue")  # type: ignore[attr-defined]
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_favor_mark_typeerror_ends_loop_and_logs(caplog):
    process, sd, _ = _make_process()
    failure = TypeError("mark broke")
    speech = PendingSpeech(SpeechPriority.CRITICAL, "divine cue", stinger_sound="stinger")
    with (
        _delivery_data(process),
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", side_effect=_skip_delay),
        patch(
            "background_process.db_activity_queries.get_divine_favor",
            new_callable=AsyncMock,
            return_value={"level": 25},
        ),
        patch(
            "background_process.db_mutations_divine.mark_favor_whisper_level",
            new_callable=AsyncMock,
            side_effect=failure,
        ) as mark,
        caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER),
    ):
        _start_delivery(process, sd, speech)
        try:
            exception = await _failed(process._task, TypeError)
            assert exception is failure
            mark.assert_awaited_once_with("player-1", 25)
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ("not-running", "AgentSession isn't running"),
        ("closing", "AgentSession is closing, cannot use generate_reply()"),
    ],
)
@pytest.mark.asyncio
async def test_real_session_shutdown_state_is_tolerated(caplog, state, message):
    session = AgentSession(max_tool_steps=5)
    if state == "closing":
        session._activity = AgentActivity(Agent(instructions="plain"), session)
    sd = SessionData(player_id="player-1", location_id="accord_guild_hall")
    process = BackgroundProcess(session, sd)
    speech = PendingSpeech(SpeechPriority.ROUTINE, "shutdown cue")
    with _delivery_data(process), caplog.at_level(logging.WARNING, logger=BACKGROUND_LOGGER):
        waiting = _start_delivery(process, sd, speech)
        try:
            await _wait(waiting)
            assert process._task is not None and not process._task.done()
            warnings = _warning_records(caplog)
            assert len(warnings) == 1 and message in warnings[0].getMessage()
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_other_generate_reply_runtimeerror_ends_loop_and_logs(caplog):
    process, sd, _ = _make_process()
    failure = RuntimeError("reply invariant broke")
    process._session.generate_reply.side_effect = failure  # type: ignore[attr-defined]
    speech = PendingSpeech(SpeechPriority.ROUTINE, "ordinary cue")
    with _delivery_data(process), caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        _start_delivery(process, sd, speech)
        try:
            exception = await _failed(process._task, RuntimeError)
            assert exception is failure
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_failed_speech_handle_warns_and_loop_survives(caplog):
    process, sd, _ = _make_process()
    sd.companion = MagicMock(last_speech_time=0)
    failure = OSError("generation failed")
    process._session.generate_reply.side_effect = lambda **_kwargs: completed_handle(failure)  # type: ignore[attr-defined]
    speech = PendingSpeech(SpeechPriority.CRITICAL, "failed cue", stinger_sound="stinger")
    with (
        _delivery_data(process),
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", side_effect=_skip_delay),
        patch("background_process.is_companion_cue", return_value=False) as cue_check,
        patch(
            "background_process.db_activity_queries.get_divine_favor", new_callable=AsyncMock, return_value=None
        ) as get_favor,
        caplog.at_level(logging.INFO, logger=BACKGROUND_LOGGER),
    ):
        waiting = _start_delivery(process, sd, speech)
        try:
            await _wait(waiting)
            assert process._task is not None and not process._task.done()
            warnings = _warning_records(caplog)
            assert len(warnings) == 1
            assert "generation failed" in warnings[0].getMessage()
            assert "CRITICAL" in warnings[0].getMessage()
            assert not any(record.message.startswith("Proactive speech delivered") for record in caplog.records)
            get_favor.assert_not_awaited()
            assert cue_check.call_count == 1
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_transient_favor_read_failure_warns_and_loop_survives(caplog):
    process, sd, _ = _make_process()
    failure = asyncpg.PostgresError("favor unavailable")
    speech = PendingSpeech(SpeechPriority.CRITICAL, "divine cue", stinger_sound="stinger")
    with (
        _delivery_data(process),
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", side_effect=_skip_delay),
        patch(
            "background_process.db_activity_queries.get_divine_favor",
            new_callable=AsyncMock,
            side_effect=failure,
        ),
        caplog.at_level(logging.WARNING, logger=BACKGROUND_LOGGER),
    ):
        waiting = _start_delivery(process, sd, speech)
        try:
            await _wait(waiting)
            assert process._task is not None and not process._task.done()
            warnings = _warning_records(caplog)
            assert len(warnings) == 1
            assert warnings[0].message == "Failed to mark favor whisper level"
            assert warnings[0].exc_info is not None
            assert warnings[0].exc_info[1] is failure
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_apply_warm_failure_ends_loop_and_logs(caplog):
    process, sd, agent = _make_process()
    initial_applied = asyncio.Event()

    async def update(_instructions):
        if agent.update_instructions.await_count == 1:
            initial_applied.set()
            return
        raise RuntimeError("apply broke")

    agent.update_instructions.side_effect = update
    with _background_data(), caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        process.start()
        try:
            await _wait(initial_applied)
            _publish_rebuild(sd)
            exception = await _failed(process._task, RuntimeError)
            assert str(exception) == "apply broke"
            _assert_failure_record(caplog, exception)
            assert agent.update_instructions.await_count == 2
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_plain_livekit_agent_is_fatal_by_design(caplog):
    process, _, _ = _make_process(Agent(instructions="plain"))
    with _background_data(), caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        process.start()
        try:
            exception = await _failed(process._task, AttributeError)
            assert "static_prompt" in str(exception)
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_rider_prefetch_oserror_logs_and_rebuilds_continue(caplog):
    process, sd, agent = _make_process()
    initial_applied = asyncio.Event()
    rebuilt = asyncio.Event()

    async def update(_instructions):
        (initial_applied if agent.update_instructions.await_count == 1 else rebuilt).set()

    agent.update_instructions.side_effect = update
    with _background_data() as mocks, caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        mocks.rider.side_effect = OSError("rider unavailable")
        process.start()
        try:
            await _wait(initial_applied)
            _publish_rebuild(sd)
            await _wait(rebuilt)
            assert process._task is not None and not process._task.done()
            assert agent.update_instructions.await_count == 2
            records = [r for r in caplog.records if r.name == BACKGROUND_LOGGER and r.levelno == logging.ERROR]
            assert len(records) == 1
            assert records[0].exc_info is not None
            assert isinstance(records[0].exc_info[1], OSError)
        finally:
            await _finish(process)


@pytest.mark.parametrize(
    "failure",
    [
        OSError("fetch unavailable"),
        TimeoutError("fetch timed out"),
        asyncpg.PostgresError("postgres unavailable"),
        asyncpg.InterfaceError("connection unavailable"),
    ],
    ids=["oserror", "timeout", "postgres", "interface"],
)
@pytest.mark.asyncio
async def test_tolerated_fetch_failure_logs_and_next_rebuild_succeeds(caplog, failure):
    process, sd, agent = _make_process()
    initial_applied = asyncio.Event()
    rebuilt = asyncio.Event()
    waiting_for_next_event = asyncio.Event()
    location_calls = 0
    bus_get_calls = 0
    real_get = sd.event_bus.get

    async def get_location(_location_id):
        nonlocal location_calls
        location_calls += 1
        if location_calls == 2:
            raise failure
        return {"name": "Guild Hall"}

    async def update(_instructions):
        (initial_applied if agent.update_instructions.await_count == 1 else rebuilt).set()

    async def get_event(timeout: float = 30.0):
        nonlocal bus_get_calls
        bus_get_calls += 1
        if bus_get_calls == 2:
            waiting_for_next_event.set()
        return await real_get(timeout)

    agent.update_instructions.side_effect = update
    sd.event_bus.get = get_event
    with _background_data() as mocks, caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        mocks.location.side_effect = get_location
        process.start()
        try:
            await _wait(initial_applied)
            _publish_rebuild(sd)
            await _wait(waiting_for_next_event)
            assert agent.update_instructions.await_count == 1
            _publish_rebuild(sd)
            await _wait(rebuilt)
            assert process._task is not None and not process._task.done()
            records = [r for r in caplog.records if r.name == BACKGROUND_LOGGER and r.levelno == logging.ERROR]
            assert len(records) == 1
            assert records[0].message == "Warm layer data fetch failed"
            assert records[0].exc_info is not None
            assert records[0].exc_info[1] is failure
            assert agent.update_instructions.await_count == 2
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_build_keyerror_ends_loop_and_logs(caplog):
    process, sd, agent = _make_process()
    initial_applied = asyncio.Event()

    async def update(_instructions):
        initial_applied.set()

    agent.update_instructions.side_effect = update
    with _background_data() as mocks, caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        mocks.build.side_effect = ["warm-start", KeyError("missing field")]
        process.start()
        try:
            await _wait(initial_applied)
            _publish_rebuild(sd)
            exception = await _failed(process._task, KeyError)
            assert exception.args == ("missing field",)
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.parametrize("site", ["rider", "location"], ids=["rider-prefetch", "fetch-fan-out"])
@pytest.mark.asyncio
async def test_untolerated_fetch_error_ends_loop_and_logs(caplog, site):
    process, _, _ = _make_process()
    with _background_data() as mocks, caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        getattr(mocks, site).side_effect = KeyError("missing field")
        process.start()
        try:
            exception = await _failed(process._task, KeyError)
            _assert_failure_record(caplog, exception)
        finally:
            await _finish(process)


@pytest.mark.asyncio
async def test_session_cancellation_logs_no_error(caplog):
    process, _, agent = _make_process()
    initial_applied = asyncio.Event()
    agent.update_instructions.side_effect = lambda _instructions: initial_applied.set()
    with _background_data(), caplog.at_level(logging.ERROR, logger=BACKGROUND_LOGGER):
        process.start()
        await _wait(initial_applied)
        await process.stop()
        await asyncio.sleep(0)

    # Every logger, not just ours: a done-callback that raises is reported by asyncio's own logger.
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
