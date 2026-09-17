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
