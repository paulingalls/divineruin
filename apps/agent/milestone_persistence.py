"""DB persistence for the M2.3 milestone system.

Holds the player-state write for the L5 specialization choice. Lives in its own
module (not db_mutations.py) because db_mutations.py is at the 500-line cap — the
same rationale as ability_persistence.py (decision ability-persistence-module).
Milestone grant markers (e.g. the L10 extra_attack flag) reuse the existing
db_mutations.set_player_flag, so they need no function here.

set_player_specialization is write-once at the call site: resolve_milestone
(milestone_tools.py) reads players.data.specialization under a FOR UPDATE lock and
rejects a second L5 resolution before calling this, so the choice is immutable.
"""

import json

import asyncpg

import db


async def set_player_specialization(
    player_id: str,
    specialization_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the player's chosen L5 specialization id into players.data.

    Mirrors ability_persistence.update_player_resources' jsonb_set idiom. Caller
    enforces immutability (rejects when players.data.specialization is already set);
    pass a transactional conn so the write commits with the rest of the resolution.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{specialization}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(specialization_id),
    )
