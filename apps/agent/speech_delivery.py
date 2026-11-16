"""Shared delivery boundary for ``AgentSession.generate_reply`` speech."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from livekit.agents import StopResponse, llm

if TYPE_CHECKING:
    from livekit.agents import AgentSession

GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS = frozenset(
    {
        ("AgentSession isn't running",),
        ("AgentSession is closing, cannot use generate_reply()",),
        # `AgentSession.current_agent`'s wording for the same state, still spelled after the
        # class livekit renamed away from.
        ("VoiceAgent isn't running",),
    }
)


async def deliver_speech(
    session: AgentSession,
    instructions: str,
    logger: logging.Logger,
    description: str,
    failure_level: int = logging.WARNING,
    revoked: Callable[[], Awaitable[object]] | None = None,
    tool_choice: str | None = None,
) -> bool:
    """Speak ``instructions`` through ``session``; False when the player heard nothing.

    ``failure_level`` is WARNING for the background loops, which get another turn at their
    next poll, and ERROR at the session entrypoint, where the lost speech was the session's
    only opening and nothing will retry it. A session already shutting down stays a WARNING
    either way: no speech was owed.
    """
    kwargs: dict[str, object] = {"instructions": instructions}
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return await _deliver(session, logger, description, failure_level, revoked=revoked, **kwargs)


async def deliver_player_turn(
    session: AgentSession,
    user_input: str,
    logger: logging.Logger,
    description: str,
    failure_level: int = logging.ERROR,
    revoked: Callable[[], Awaitable[object]] | None = None,
) -> bool:
    """Answer one authenticated player turn; False when that player heard nothing.

    ERROR by default: unlike the background loops nothing re-offers a spoken turn, and the
    multiplayer consumer must keep serving the other players rather than die on one failure.

    Runs the agent's ``on_user_turn_completed`` first, against a throwaway copy of its chat
    context, exactly as ``agent_activity._user_turn_completed_impl`` does. livekit reaches
    that hook only from ``audio_recognition``'s end-of-turn, and the gameplay session takes
    no room audio of its own (``session_startup.gameplay_room_options``), so without this the
    DM answers a delivered turn with no hot layer at all.
    """
    try:
        agent = session.current_agent
        turn_ctx = agent.chat_ctx.copy()
    except RuntimeError as exc:
        if exc.args not in GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS:
            raise
        logger.warning("%s skipped: %s", description, exc)
        return False

    message = llm.ChatMessage(role="user", content=[user_input])
    try:
        await agent.on_user_turn_completed(turn_ctx, message)
    except StopResponse:
        # A deliberate no-reply, not a defect: livekit answers this hook the same way
        # (agent_activity._user_turn_completed_impl), so it must not enter the record at
        # failure_level beside a hook that actually broke.
        logger.info("%s declined by %s", description, agent.label)
        return False
    except Exception as exc:
        logger.log(failure_level, "%s hot layer failed: %s", description, exc)
        return False

    return await _deliver(
        session,
        logger,
        description,
        failure_level,
        revoked=revoked,
        user_input=message,
        chat_ctx=turn_ctx,
    )


DRAINING = "cannot schedule new speech, the speech scheduling is draining/pausing, the speech will be cancelled"
DRAIN_RETRY_SECS = 60.0


async def _generate_reply(session: AgentSession, reply_kwargs: dict[str, object]):
    # LiveKit refuses new speech while draining the old agent during a handoff; retry that
    # exact refusal. A drain outlasted 5 seconds on a loaded machine, so the bound is sized
    # for a stuck handoff, not a slow one.
    async with asyncio.timeout(DRAIN_RETRY_SECS):
        while True:
            try:
                return session.generate_reply(**reply_kwargs)  # type: ignore[arg-type]
            except RuntimeError as exc:
                if exc.args != (DRAINING,):
                    raise
                await asyncio.sleep(0.02)


async def _deliver(
    session: AgentSession,
    logger: logging.Logger,
    description: str,
    failure_level: int,
    revoked: Callable[[], Awaitable[object]] | None = None,
    **reply_kwargs: object,
) -> bool:
    revocation_task = asyncio.ensure_future(revoked()) if revoked is not None else None
    request = asyncio.create_task(_generate_reply(session, reply_kwargs))
    handle = None
    handle_task = None
    try:
        if revocation_task is not None:
            done, _ = await asyncio.wait((request, revocation_task), return_when=asyncio.FIRST_COMPLETED)
            if revocation_task in done and not request.done():
                return False
        try:
            handle = await request
        except RuntimeError as exc:
            if exc.args not in GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS:
                raise
            logger.warning("%s skipped: %s", description, exc)
            return False
        except TimeoutError:
            logger.error("%s dropped: the handoff never finished draining", description)
            return False
        handle_task = asyncio.ensure_future(handle)
        if revocation_task is not None:
            done, _ = await asyncio.wait((handle_task, revocation_task), return_when=asyncio.FIRST_COMPLETED)
            if revocation_task in done:
                if not handle_task.done():
                    handle.interrupt(force=True)
                revocation_task.result()
        await handle_task
        if (failure := handle.exception()) is not None:
            logger.log(failure_level, "%s failed: %s", description, failure)
            return False
        return True
    finally:
        # Cancellation can arrive during handoff retry or after LiveKit accepted a handle.
        if handle is None and request.done() and not request.cancelled() and request.exception() is None:
            handle = request.result()
        if handle is not None and (handle_task is None or not handle_task.done()):
            handle.interrupt(force=True)
        tasks: list[asyncio.Future] = [task for task in (request, handle_task, revocation_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
