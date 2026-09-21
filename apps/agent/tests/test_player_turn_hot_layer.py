"""The per-turn layer a delivered player turn must still run.

Gameplay speech reaches the DM as text through MultiParticipantTranscriber, and
`generate_reply(user_input=...)` lands in `_pipeline_reply_task` directly
(agent_activity._generate_reply). livekit only runs `Agent.on_user_turn_completed` from
`audio_recognition`'s end-of-turn hook, and the gameplay session takes no room audio
(session_startup.gameplay_room_options), so nothing else can run it.
"""

import asyncio
import logging
from typing import Any, cast

import pytest
from livekit.agents import Agent, StopResponse, llm

from speech_delivery import deliver_player_turn

HOT_LINE = "[COMBAT Round 2: Kael(healthy)]"


class HotLayerAgent(Agent):
    def __init__(self, raises: BaseException | None = None):
        super().__init__(instructions="test")
        self._raises = raises
        self.seen: list[str] = []

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        self.seen.append(new_message.text_content or "")
        if self._raises is not None:
            raise self._raises
        turn_ctx.add_message(role="assistant", content=HOT_LINE)


class DoneHandle:
    def exception(self):
        return None

    def __await__(self):
        return asyncio.sleep(0).__await__()


class ReplyingSession:
    """Fakes only the `generate_reply` boundary; the agent it hands back is the real one."""

    def __init__(self, agent: Agent | None, *, agent_error: BaseException | None = None):
        self._agent = agent
        self._agent_error = agent_error
        self.calls: list[dict] = []

    @property
    def current_agent(self) -> Agent:
        if self._agent_error is not None:
            raise self._agent_error
        assert self._agent is not None
        return self._agent

    def generate_reply(self, **kwargs):
        self.calls.append(kwargs)
        return DoneHandle()


async def _deliver(session: ReplyingSession, text: str = "I swing at Grosh.") -> bool:
    return await deliver_player_turn(cast(Any, session), text, logging.getLogger("test"), "DM turn")


def _messages(chat_ctx: llm.ChatContext) -> list[str | None]:
    return [item.text_content for item in chat_ctx.items if isinstance(item, llm.ChatMessage)]


@pytest.mark.asyncio
async def test_delivered_turn_runs_the_agents_hot_layer_into_the_request_context():
    agent = HotLayerAgent()
    session = ReplyingSession(agent)

    assert await _deliver(session) is True

    assert agent.seen == ["I swing at Grosh."]
    kwargs = session.calls[0]
    assert _messages(kwargs["chat_ctx"]) == [HOT_LINE]
    assert kwargs["user_input"].text_content == "I swing at Grosh."


@pytest.mark.asyncio
async def test_hot_layer_edits_do_not_leak_into_the_agents_own_history():
    """livekit hands the hook a throwaway copy (agent_activity:2801); the combat round line
    must not land in the cached prefix (combat_agent.on_user_turn_completed, debt ce06dd8c)."""
    agent = HotLayerAgent()

    assert await _deliver(ReplyingSession(agent)) is True

    assert _messages(agent.chat_ctx) == []


@pytest.mark.asyncio
async def test_a_hook_declining_the_turn_suppresses_the_reply_without_reporting_a_failure(caplog):
    agent = HotLayerAgent(raises=StopResponse())
    session = ReplyingSession(agent)

    with caplog.at_level(logging.INFO):
        assert await _deliver(session) is False

    assert session.calls == []
    assert [record.levelno for record in caplog.records] == [logging.INFO]
    assert "declined" in caplog.text


@pytest.mark.asyncio
async def test_a_failing_hook_is_logged_and_does_not_reach_the_caller(caplog):
    agent = HotLayerAgent(raises=ValueError("hot layer blew up"))
    session = ReplyingSession(agent)

    with caplog.at_level(logging.ERROR):
        assert await _deliver(session) is False

    assert session.calls == []
    assert "hot layer blew up" in caplog.text


@pytest.mark.asyncio
async def test_a_session_that_has_stopped_running_skips_the_turn_instead_of_raising(caplog):
    """`current_agent` raises its own wording, not generate_reply's — the multiplayer consumer
    must survive a turn that arrives as the DM session closes (multiplayer_input._run)."""
    session = ReplyingSession(None, agent_error=RuntimeError("VoiceAgent isn't running"))

    with caplog.at_level(logging.WARNING):
        assert await _deliver(session) is False

    assert session.calls == []
    assert "VoiceAgent isn't running" in caplog.text


@pytest.mark.asyncio
async def test_an_unexpected_session_runtime_error_still_raises():
    session = ReplyingSession(None, agent_error=RuntimeError("room handle exploded"))

    with pytest.raises(RuntimeError, match="room handle exploded"):
        await _deliver(session)
