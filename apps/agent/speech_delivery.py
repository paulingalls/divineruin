"""Shared delivery boundary for ``AgentSession.generate_reply`` speech."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from livekit.agents import AgentSession

GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS = frozenset(
    {
        ("AgentSession isn't running",),
        ("AgentSession is closing, cannot use generate_reply()",),
    }
)


async def deliver_speech(
    session: AgentSession,
    instructions: str,
    logger: logging.Logger,
    description: str,
    failure_level: int = logging.WARNING,
) -> bool:
    """Speak ``instructions`` through ``session``; False when the player heard nothing.

    ``failure_level`` is WARNING for the background loops, which get another turn at their
    next poll, and ERROR at the session entrypoint, where the lost speech was the session's
    only opening and nothing will retry it. A session already shutting down stays a WARNING
    either way: no speech was owed.
    """
    return await _deliver(session, logger, description, failure_level, instructions=instructions)


async def deliver_player_turn(
    session: AgentSession,
    user_input: str,
    logger: logging.Logger,
    description: str,
    failure_level: int = logging.ERROR,
    revoked: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Answer one authenticated player turn; False when that player heard nothing.

    ERROR by default: unlike the background loops nothing re-offers a spoken turn, and the
    multiplayer consumer must keep serving the other players rather than die on one failure.
    """
    return await _deliver(
        session,
        logger,
        description,
        failure_level,
        revoked=revoked,
        user_input=user_input,
    )


async def _deliver(
    session: AgentSession,
    logger: logging.Logger,
    description: str,
    failure_level: int,
    revoked: Callable[[], Awaitable[None]] | None = None,
    **reply_kwargs: object,
) -> bool:
    try:
        handle = session.generate_reply(**reply_kwargs)  # type: ignore[arg-type]
    except RuntimeError as exc:
        if exc.args not in GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS:
            raise
        logger.warning("%s skipped: %s", description, exc)
        return False

    if revoked is None:
        await handle
    else:
        handle_task = asyncio.ensure_future(handle)
        revocation_task = asyncio.ensure_future(revoked())
        try:
            done, _pending = await asyncio.wait(
                (handle_task, revocation_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if revocation_task in done and not handle_task.done():
                handle.interrupt(force=True)
            await handle_task
            if revocation_task in done:
                revocation_task.result()
        except asyncio.CancelledError:
            handle.interrupt(force=True)
            handle_task.cancel()
            await asyncio.gather(handle_task, return_exceptions=True)
            raise
        finally:
            revocation_task.cancel()
            await asyncio.gather(revocation_task, return_exceptions=True)
    if (failure := handle.exception()) is not None:
        logger.log(failure_level, "%s failed: %s", description, failure)
        return False
    return True
