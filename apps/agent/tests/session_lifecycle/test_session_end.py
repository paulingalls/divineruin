"""The session's END — the summary the player hears, fired when the SESSION closes.

Not when an agent exits: an agent's ``on_exit`` runs on every mode handoff
(``AgentActivity.drain`` awaits it, agent_activity.py:919-932), so session-scoped work
placed there fires on the way into every fight.
"""

import asyncio
import contextlib
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import AgentSession, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.voice.events import CloseEvent, CloseReason

import event_types as E
from background_process import BackgroundProcess
from exploration_agent import ExplorationAgent
from session_data import SessionData

# apps/mobile/src/audio/game-event-handler.ts:266-286 reads these off the SESSION_END
# payload and populates the summary screen from them. A key the producer spells
# differently renders as an empty stat, silently.
CLIENT_KEYS = frozenset(
    {"summary", "xp_earned", "items_found", "quest_progress", "duration", "next_hooks", "story_moments"}
)


def _session_data() -> SessionData:
    """SessionData with a room that accepts a real ``publish_game_event`` (game_events.py:50-58)."""
    room = MagicMock()
    room.isconnected.return_value = True
    room.local_participant.publish_data = AsyncMock()
    return SessionData(player_id="player_1", location_id="accord_guild_hall", room=room)


@contextlib.contextmanager
def _quiet_session(*, real_background: bool):
    """Silence everything the recap is not about — the HUD tap, the warm loop's DB reads, the
    session-init query, and the summary's LLM and story-moment edges.

    ``real_background`` keeps ``BackgroundProcess.start()`` real (only its loop body is
    stubbed) so the close handlers register on the real session emitter — that registration
    is what the tests below are about.
    """
    background = (
        patch.object(BackgroundProcess, "_run", new_callable=AsyncMock)
        if real_background
        else patch("exploration_agent.BackgroundProcess")
    )
    with (
        background,
        patch("exploration_agent.start_specialization_tap"),
        patch(
            "exploration_agent.db_session_queries.get_session_init_payload",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None) as mock_llm,
        patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
    ):
        yield mock_llm


async def _enter() -> ExplorationAgent:
    """What LiveKit does on a handback: a NEW agent enters over the same SessionData."""
    agent = ExplorationAgent()
    await agent.on_enter()
    return agent


def _session_end_payloads(sd: SessionData) -> list[dict]:
    return [e.payload for e in sd.event_bus.drain() if e.event_type == E.SESSION_END]


class _EndStream(llm.LLMStream):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.model = model

    async def _run(self):
        self.model.calls += 1
        if self.model.calls == 1:
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name="end_session", arguments=json.dumps({"reason": "goodbye"}), call_id=uuid.uuid4().hex
                    )
                ],
            )
        else:
            delta = llm.ChoiceDelta(role="assistant", content="Until next time.")
        self._event_ch.send_nowait(llm.ChatChunk(id=uuid.uuid4().hex, delta=delta))


class _EndModel(llm.LLM):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_kwargs):
        return _EndStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class TestEndSessionReachesTheCloseEmit:
    """A real ExplorationAgent turn reaches the session close event after the wrap-up."""

    @pytest.mark.asyncio
    async def test_last_member_goodbye_closes_the_session(self):
        sd = _session_data()
        model = _EndModel()
        session = AgentSession(llm=model, max_tool_steps=5, userdata=sd)
        session.output.set_audio_enabled(False)
        closed = asyncio.Event()
        session.on("close", lambda _ev: closed.set())
        agent = ExplorationAgent()

        with (
            _quiet_session(real_background=True),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock) as save,
            patch("exploration_agent.publish_game_event", new_callable=AsyncMock),
        ):
            await session.start(agent)
            await session.run(user_input="goodbye")
            await asyncio.wait_for(closed.wait(), timeout=5.0)
            assert sd.session_end_task is not None
            await sd.session_end_task
        assert model.calls == 2
        save.assert_awaited_once()
        assert save.await_args is not None and save.await_args.args[0] == "player_1"


class TestTheRecapFiresOncePerSession:
    """AC2. The close event is REAL — a ``CloseEvent`` dispatched by a real ``AgentSession``'s
    emitter, which is what LiveKit sends and what checks the handler's arity.

    These tests hand-produce that event rather than reaching it through ``aclose()``, so on
    their own they check registration and dispatch, not the whole path.
    ``TestEndSessionReachesTheCloseEmit`` above is what proves the event actually arrives;
    neither substitutes for the other.
    """

    @pytest.mark.asyncio
    async def test_a_real_close_fires_the_recap_once(self):
        sd = _session_data()
        session = AgentSession(max_tool_steps=5, userdata=sd)

        with (
            _quiet_session(real_background=True),
            patch.object(ExplorationAgent, "session", property(lambda _s: session)),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock) as mock_save,
        ):
            await _enter()
            session.emit("close", CloseEvent(reason=CloseReason.JOB_SHUTDOWN))
            assert sd.session_end_task is not None
            await sd.session_end_task

        assert len(_session_end_payloads(sd)) == 1
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_two_fights_do_not_multiply_the_recap(self):
        """A handback builds a NEW ExplorationAgent over the SAME SessionData, so anything
        session-scoped that on_enter rebuilds gets a second registration on the same emitter.

        The mutation this reds against is dropping ``if sd.background is None`` — a fresh
        ``BackgroundProcess`` per handback, hence a distinct bound ``_on_session_end`` per
        fight. Re-registering the SAME instance's handler does NOT red here and is not a
        defect: ``EventEmitter._events`` is a ``Dict[T, Set[Callable]]`` and ``on`` calls
        ``.add`` (rtc/event_emitter.py:15,165), so an identical bound method collapses to one.
        """
        sd = _session_data()
        session = AgentSession(max_tool_steps=5, userdata=sd)

        with (
            _quiet_session(real_background=True),
            patch.object(ExplorationAgent, "session", property(lambda _s: session)),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock) as mock_save,
        ):
            agent = await _enter()
            for _ in range(2):  # two fights
                await agent.on_exit()
                agent = await _enter()

            session.emit("close", CloseEvent(reason=CloseReason.JOB_SHUTDOWN))
            assert sd.session_end_task is not None
            await sd.session_end_task

        assert len(_session_end_payloads(sd)) == 1
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_payload_carries_every_key_the_client_reads(self):
        sd = _session_data()
        session = AgentSession(max_tool_steps=5, userdata=sd)

        with (
            _quiet_session(real_background=True),
            patch.object(ExplorationAgent, "session", property(lambda _s: session)),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock) as mock_save,
        ):
            await _enter()
            session.emit("close", CloseEvent(reason=CloseReason.JOB_SHUTDOWN))
            assert sd.session_end_task is not None
            await sd.session_end_task

        (payload,) = _session_end_payloads(sd)
        assert set(payload) >= CLIENT_KEYS, f"missing: {sorted(CLIENT_KEYS - set(payload))}"
        # The stored row is the same dict the client got — one summary, not two shapes.
        assert mock_save.await_args is not None
        assert mock_save.await_args.args == (sd.player_id, sd.session_id, payload)

    @pytest.mark.asyncio
    async def test_the_recap_covers_the_whole_session_not_the_last_agent(self, tmp_path):
        """Both inputs are read off SessionData, so a handback cannot restart them: the
        duration is measured from the session's start and the transcript is the session's
        one file, written to before the first handoff.

        _default_log_path is stubbed to hand out DISTINCT paths: the real one is second-
        granular, so two agents entering in the same second land on one file anyway and the
        transcript half of this guard passes without the seam existing (constraint 1).
        """
        minted = iter([str(tmp_path / "first.log"), str(tmp_path / "second.log")])
        sd = _session_data()
        sd.session_start_time = time.time() - 600
        session = AgentSession(max_tool_steps=5, userdata=sd)

        with (
            _quiet_session(real_background=True) as mock_llm,
            patch.object(ExplorationAgent, "session", property(lambda _s: session)),
            patch("transcript._default_log_path", side_effect=lambda: next(minted)),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock),
        ):
            agent = await _enter()
            assert agent._transcript is not None
            await agent._transcript.log_player("I open the crypt door.")
            started_at = sd.session_start_time

            await agent.on_exit()  # the handoff into combat
            await _enter()  # the handback, a fresh agent
            assert sd.session_start_time == started_at

            session.emit("close", CloseEvent(reason=CloseReason.JOB_SHUTDOWN))
            assert sd.session_end_task is not None
            await sd.session_end_task

        (payload,) = _session_end_payloads(sd)
        assert payload["duration"] == pytest.approx(600, abs=5)
        # The pre-fight turn is still in the transcript the recap summarises.
        assert mock_llm.await_args is not None
        assert "I open the crypt door." in mock_llm.await_args.kwargs["transcript_tail"]
