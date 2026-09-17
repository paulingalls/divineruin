"""Shared delivery boundary for ``AgentSession.generate_reply`` speech."""

from __future__ import annotations

import logging
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
    try:
        handle = session.generate_reply(instructions=instructions)
    except RuntimeError as exc:
        if exc.args not in GENERATE_REPLY_SESSION_UNAVAILABLE_ARGS:
            raise
        logger.warning("%s skipped: %s", description, exc)
        return False

    await handle
    if (failure := handle.exception()) is not None:
        logger.log(failure_level, "%s failed: %s", description, failure)
        return False
    return True
