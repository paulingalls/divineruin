"""Foretold Words forecasts and their session-scoped spent markers."""

import json
from typing import TypedDict

import asyncpg
from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_queries
import social_resolution
from condition_consume import serialize_combat_check
from disposition import resolve_disposition
from patron_synergy import has_engine_synergy
from rules_engine import dc_for_tier
from session_data import SessionData
from skill_fate import StaleSkillOperation
from tool_support import _validate_id

CLAUSE = "zhael_foretold_words"
CLAUSE_RECEIPT = {"clause_id": CLAUSE, "clause_name": "Foretold Words"}


class Binding(TypedDict):
    skill: str
    dc: int


@serialize_combat_check
async def foretell(
    context: RunContext[SessionData],
    npc_id: str,
    skill: str,
    difficulty: str,
    *,
    queries=db_queries,
    content=db_content_queries,
) -> str:
    _validate_id(npc_id, "npc_id")
    if skill not in social_resolution.DISPOSITION_SHIFT:
        raise ToolError(f"Unknown social skill: {skill!r}.")
    try:
        base_dc = dc_for_tier(difficulty.lower())
    except ValueError as error:
        raise ToolError(str(error)) from error

    session = context.userdata
    player_id = session.acting_player_id
    async with db.transaction() as conn:
        player = await queries.get_player(player_id, conn=conn, for_update=True)
        session.validate_acting_player(player_id)
        if player is None or not has_engine_synergy(player, CLAUSE):
            raise ToolError("Foretold Words is available only to a Zhael bard or diplomat.")
        if await content.get_npc(npc_id) is None:
            raise ToolError(f"Unknown NPC '{npc_id}'.")
        disposition = await resolve_disposition(
            npc_id, player_id, conn=conn, for_update=True, queries_mod=queries, content_mod=content
        )
        dc = social_resolution.social_dc(base_dc, disposition)
        binding = Binding(skill=skill, dc=dc)
        status = await conn.execute(
            "INSERT INTO zhael_foretold_words (player_id, npc_id, session_id, data) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT DO NOTHING",
            player_id,
            npc_id,
            session.session_id,
            json.dumps({"binding": binding}),
        )
        if status == "INSERT 0 0":
            raise ToolError(f"Foretold Words already foretold a check against '{npc_id}' this session.")

    return json.dumps(
        {
            **CLAUSE_RECEIPT,
            "npc_id": npc_id,
            **binding,
            "dm_cue": f"Tell the player that Foretold Words reveals a difficulty of {dc} for this {skill} check.",
        }
    )


async def pending(player_id: str, npc_id: str, session_id: str) -> Binding | None:
    pool = await db.get_pool()
    value = await pool.fetchval(
        "SELECT data->'binding' FROM zhael_foretold_words WHERE player_id=$1 AND npc_id=$2 AND session_id=$3",
        player_id,
        npc_id,
        session_id,
    )
    return json.loads(value) if value is not None else None


async def clear(conn: asyncpg.Connection, player_id: str, npc_id: str, session_id: str, binding: Binding) -> None:
    status = await conn.execute(
        """UPDATE zhael_foretold_words SET data='{"binding":null}'::jsonb
           WHERE player_id=$1 AND npc_id=$2 AND session_id=$3 AND data->'binding'=$4::jsonb""",
        player_id,
        npc_id,
        session_id,
        json.dumps(binding),
    )
    if status != "UPDATE 1":
        raise StaleSkillOperation("Foretold Words no longer has that pending check.")


async def project(player_id: str, session_id: str) -> dict:
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT npc_id, data->'binding' AS binding FROM zhael_foretold_words "
        "WHERE player_id=$1 AND session_id=$2 ORDER BY npc_id",
        player_id,
        session_id,
    )
    return {
        **CLAUSE_RECEIPT,
        "invocation_hint": 'Use check(roll={kind: "foretell_social", npc_id, skill, difficulty}) before the attempt.',
        "foretold_npcs": [{"npc_id": row["npc_id"], "binding": json.loads(row["binding"])} for row in rows],
    }
