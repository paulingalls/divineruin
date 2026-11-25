"""Commit the Lost Scout's narration receipt and outcomes with combat."""

from livekit.agents.llm import ToolError

import combat_round_checkpoint
import db_content_queries
import lost_scout_scene as scene


def owns(state):
    return state.encounter_id == scene.SCOUT and state.location_id == scene.INNER


async def locked_record(session, *, queries, conn):
    player = await queries.get_player(session.primary_player_id, conn=conn, for_update=True)
    return scene.read(player)


async def start(session, state, *, mutations, queries, db_mod):
    actor_id = session.acting_player_id
    async with db_mod.transaction() as conn:
        record = await locked_record(session, queries=queries, conn=conn)
        if record["cleared"]:
            raise ToolError("The Lost Scout has already been defeated.")
        session.validate_acting_player(actor_id)
        record["outcome"] = "fought"
        await scene.write(session.primary_player_id, record, mutations=mutations, conn=conn)
        await combat_round_checkpoint.capture(session, state, conn=conn, mutations=mutations, entry=True)


async def residue(session, state, *, mutations, queries, conn):
    if not owns(state):
        return None
    record = await locked_record(session, queries=queries, conn=conn)
    if record["residue_delivered"]:
        return None
    cue = await scene.scene_text(db_content_queries, "residue", conn=conn)
    record["residue_delivered"] = True
    await scene.write(session.primary_player_id, record, mutations=mutations, conn=conn)
    return cue


async def end(session, state, outcome, combat_cleared, *, mutations, queries, conn):
    if not owns(state):
        return
    cleared = outcome == "victory" and combat_cleared
    if not cleared and outcome != "fled":
        return
    record = await locked_record(session, queries=queries, conn=conn)
    if cleared:
        record["cleared"] = True
    else:
        record["outcome"] = "fled"
    await scene.write(session.primary_player_id, record, mutations=mutations, conn=conn)
