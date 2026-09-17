from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from livekit.agents.llm import ToolError

import combat_phase
from combat_events import scratch_guard
from session_data import SessionData


class PrevalidationRefusal(Exception):
    def __init__(self, error: ToolError):
        self.error = error


@asynccontextmanager
async def phase_transaction_with_recovery(
    session: SessionData,
    committed_state,
    *,
    db_mod,
    mutations,
) -> AsyncIterator[Any]:
    try:
        async with scratch_guard(session), db_mod.transaction() as conn:
            yield conn
    except PrevalidationRefusal as refusal:
        reopened = combat_phase.reopen_declaration(committed_state)
        async with db_mod.transaction() as conn:
            await mutations.save_combat_state(reopened.combat_id, reopened.to_dict(), conn=conn)
        session.combat_state = reopened
        raise ToolError(
            f"{refusal.error} Every declaration was cleared; re-declare the whole phase."
        ) from refusal.error
