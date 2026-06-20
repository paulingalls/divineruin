"""Combat teardown — end_combat tool."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import conditions
import db
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import resurrection
from combat_events import EventSink, emit_or_publish
from combat_support import _accrue_durability, _find_equipped, _publish_sounds, _require_combat
from db_errors import db_tool
from region_types import REGION_CITY
from session_data import CombatState, SessionData
from tool_support import SOUND_COMBAT_DEFEAT, SOUND_COMBAT_FLED, SOUND_COMBAT_VICTORY

logger = logging.getLogger("divineruin.tools")

_VALID_OUTCOMES = ("victory", "defeat", "fled")
_STINGER_SOUND = {
    "victory": SOUND_COMBAT_VICTORY,
    "defeat": SOUND_COMBAT_DEFEAT,
    "fled": SOUND_COMBAT_FLED,
}


def _merge_persistent_conditions(existing: list[dict], acquired: list[dict]) -> list[dict]:
    """Union the player's stored cross-encounter conditions with those acquired this fight.

    Combat only ACCRUES (rest clears, a later milestone), so a fight never drops a pre-existing
    condition. On a type conflict, keep the instance with the higher accrual — more ``stacks``
    (Exhausted), or higher ``stage`` (Hollowed) — so a fight that deepens an already-persisted
    Exhausted isn't silently discarded. This is approximate until combat-START load lands (debt
    1e32d78449ef): the participant doesn't carry the prior store in, so a combat-gained instance
    counts only this fight's accrual — max() is the safe floor (never lose the worse of the two)."""

    def _severity(c: dict) -> int:
        return c.get("stacks", c.get("stage", 1))

    merged = {c["type"]: c for c in existing}
    for c in acquired:
        prior = merged.get(c["type"])
        if prior is None or _severity(c) > _severity(prior):
            merged[c["type"]] = c
    return list(merged.values())


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str | tuple:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, calculates XP from defeated enemies (call award_xp separately
    with the returned total). Clears all combat state."""
    return await _end_combat_impl(context, outcome)


async def _end_combat_impl(
    context: RunContext[SessionData],
    outcome: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
    db_mod=db,
) -> str | tuple:
    """Standalone end_combat tool entry: validate, run the DB writes in their OWN transaction,
    flush the buffered events post-commit, then apply the in-memory teardown + agent handoff.

    The resolve_phase path does NOT call this — it shares its phase transaction by invoking
    _end_combat_db (in-tx) and _end_combat_finish (post-commit) directly (story-005, Seam 1)."""
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata
    cs = _require_combat(session)

    if outcome.lower() not in _VALID_OUTCOMES:
        raise ToolError(f"Invalid outcome. Must be one of: {_VALID_OUTCOMES}")
    outcome = outcome.lower()

    sink = EventSink()
    async with db_mod.transaction() as conn:
        end_data = await _end_combat_db(
            session, cs, outcome, mutations=mutations, queries=queries, conn=conn, sink=sink
        )
    await sink.flush()
    return _end_combat_finish(session, cs, outcome, end_data)


async def _end_combat_db(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    *,
    mutations,
    queries,
    conn,
    sink: EventSink,
) -> dict:
    """The DB-mutating + event-emitting half of end_combat, run INSIDE a transaction (the phase
    tx when invoked from resolve_phase, or end_combat's own). Accrues weapon durability, deletes
    the combat row, and buffers COMBAT_ENDED + the stinger into ``sink`` (released post-commit).
    Touches NO in-memory session state — that is _end_combat_finish's job, deferred to post-commit
    so a rollback leaves the session pristine. Returns the data finish needs to build the response."""
    xp_total = 0
    defeated_enemies: list[str] = []
    if outcome == "victory":
        enemy_dicts = []
        for p in cs.participants:
            if p.type == "enemy":
                enemy_dicts.append({"xp_value": p.xp_value})
                defeated_enemies.append(p.name)
        xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)

    # Accrue per-encounter weapon durability (1 hit, 2 on a crit vs a heavily-armored target),
    # hollow-doubled. Reads weapon_used_this_encounter (set live during the loop); the flag RESET
    # is deferred to _end_combat_finish so a rolled-back phase keeps it set for the retry.
    weapon_durability: dict = {}
    if session.weapon_used_this_encounter:
        inventory = await queries.get_player_inventory(session.player_id, conn=conn)
        weapon = _find_equipped(inventory, "weapon")
        if weapon is not None:
            weapon_durability = await _accrue_durability(
                session,
                session.player_id,
                weapon,
                combat_resolution.weapon_hits_for_encounter(session.weapon_crit_vs_heavy),
                is_hollow_zone=combat_resolution.is_hollow_zone(session.corruption_level),
                conn=conn,
                sink=sink,
            )

    # Persist the player's cross-encounter conditions (M4.3, story-004): the persists_across_encounters
    # ones acquired this fight (Wounded/Exhausted/Hollowed) MERGE into players.data; phase-scoped ones
    # (Prone/Stunned/…) drop with the combat row. Combat only ACCRUES persistent conditions (rest
    # clears them, a later milestone), and combat-START load is deferred, so we union with the existing
    # store rather than overwrite — else a fight would clobber a pre-combat Wounded. Skip all DB work
    # when nothing was acquired (the common case). Same tx as the row delete (atomic).
    player_part = next((p for p in cs.participants if p.type == "player"), None)
    if player_part is not None:
        acquired = [
            c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].persists_across_encounters
        ]
        if acquired:
            existing = await db_mutations_conditions.read_player_conditions(session.player_id, conn=conn)
            merged = _merge_persistent_conditions(existing, acquired)
            await db_mutations_conditions.save_player_conditions(session.player_id, merged, conn=conn)

    await mutations.delete_combat_state(cs.combat_id, conn=conn)

    # Death & resurrection (M4.4 story-003): on defeat the player died — auto-return them via Mortaen.
    # trigger_character_death records the death, applies the escalating cost, resolves the nearest
    # anchor, and revives the character (atomic with this combat-teardown tx). Hollowed-death is
    # story-007. combat_cleared = the area is no longer hostile (all enemies down even though the
    # player fell) — feeds the tier-1 cleared-battlefield anchor.
    death_context: dict | None = None
    if outcome == "defeat":
        enemies = [p for p in cs.participants if p.type == "enemy"]
        combat_cleared = bool(enemies) and all(p.is_fallen for p in enemies)
        player_data = await queries.get_player(session.player_id, conn=conn)
        if player_data is not None:
            death_context = await resurrection.resurrect_on_defeat(
                player_data, combat_cleared=combat_cleared, conn=conn
            )

    await emit_or_publish(
        sink,
        session.room,
        E.COMBAT_ENDED,
        {"combat_id": cs.combat_id, "outcome": outcome, "xp_total": xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [_STINGER_SOUND[outcome]], sink=sink)

    return {
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "weapon_durability": weapon_durability,
        "death_context": death_context,
    }


def _end_combat_finish(
    session: SessionData,
    cs: CombatState,
    outcome: str,
    end_data: dict,
) -> tuple:
    """The in-memory + handoff half of end_combat, run ONLY after the transaction commits. Resets
    the per-encounter flags, clears combat_state, records the event/memory, and returns the
    (gameplay_agent, json) handoff. No DB, no events — nothing here is reachable on a rollback."""
    xp_total = end_data["xp_total"]
    defeated_enemies = end_data["defeated_enemies"]

    session.weapon_used_this_encounter = False
    session.weapon_crit_vs_heavy = False
    session.draethar_inner_fire_used = False  # Inner Fire resets each encounter (M3.4)
    session.combat_state = None

    # On a defeat-resurrection the character was revived AT the anchor (resurrect_on_defeat wrote
    # players.data.location_id = anchor). Sync the live session so the post-death handoff agent is
    # built at the anchor, not the stale death site — AC3: the character returns at the anchor.
    death_context = end_data.get("death_context")
    if death_context is not None:
        session.location_id = death_context["anchor"]

    session.record_event(f"Combat ended: {outcome}")
    if defeated_enemies:
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {cs.location_id}: {outcome}")

    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "weapon_durability": end_data["weapon_durability"],
        "note": "Call award_xp with the xp_total to grant experience to the player." if xp_total > 0 else None,
    }
    logger.info("end_combat result: %s, xp=%d", outcome, xp_total)

    # Build gameplay agent with combat summary context for handoff
    from livekit.agents.llm import ChatContext

    from gameplay_agent import create_gameplay_agent

    summary_parts = [f"Combat resolved: {outcome}."]
    if xp_total > 0:
        summary_parts.append(f"XP earned: {xp_total}.")
    if defeated_enemies:
        summary_parts.append(f"Defeated: {', '.join(defeated_enemies)}.")

    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(summary_parts))

    agent_type = session.pre_combat_agent_type or REGION_CITY
    session.pre_combat_agent_type = None
    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps(response)
