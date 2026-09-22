"""Deterministic world effects declared by a quest stage's ``on_complete``.

Split out of quest_tools (sprint-044 close, debt 6b7339adcb41) — that module was one line
from the 500 hard max and is the file this sprint rewrote most, so the next fix on the quest
path could not land without this move first. Pure move: the parser, its five effect regexes
and the single applier, unchanged.

Each effect string is authored content, so an unparseable or unknown one WARNS and skips
rather than raising — one typo must not roll back the stage transaction that already paid
the party.
"""

import logging
import re

import asyncpg

import db_content_queries
import db_mutations
import db_mutations_reputation
import db_queries
import event_types as E
from disposition import resolve_disposition
from reputation import reputation_shift
from role_archetypes import shift_disposition
from session_data import SessionData
from world_effect_targets import COMPANION_SHORTHAND, EFFECT_NPC_MAP

logger = logging.getLogger("divineruin.tools")


_EFFECT_DISPOSITION_RE = re.compile(r"^(\w+)_disposition\s*([+-]\d+)$")
_EFFECT_CORRUPTION_RE = re.compile(r"^greyvale_corruption\s*([+-]\d+)$")
_EFFECT_EVENT_RE = re.compile(r"^event:(.+)$")
_EFFECT_MORALE_RE = re.compile(r"^(\w+)_morale\s*([+-]\d+)$")
# "<faction_id>_reputation <named_event>" — the faction-scoped analogue of the per-NPC
# disposition shorthand, but the magnitude comes from the named event (reputation_shift),
# not an inline number, so the delta lives in one place (story-002 inc 4b).
_EFFECT_REPUTATION_RE = re.compile(r"^(\w+)_reputation\s+(\w+)$")


async def _apply_world_effects(
    effects: list[str],
    session: SessionData,
    pending_events: list[tuple[str, dict]],
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    *,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    reputation_mutations=db_mutations_reputation,
    pending_corruption: dict[str, int] | None = None,
    party_ids: tuple[str, ...] | None = None,
) -> None:
    """Parse and apply deterministic world_effects from quest on_complete."""
    actor_id = session.acting_player_id
    party_ids = party_ids if party_ids is not None else tuple(session.party.member_ids)
    for effect_str in effects:
        m = _EFFECT_DISPOSITION_RE.match(effect_str)
        if m:
            shorthand, delta_str = m.group(1), int(m.group(2))
            if shorthand == COMPANION_SHORTHAND:
                if session.companion is None:
                    # Warn-and-skip, matching this function's policy for every other
                    # unresolvable effect below: this runs inside the quest-stage transaction,
                    # and refusing to write beats writing against a guessed companion.
                    logger.warning("Companion world effect with no bound companion: %s", effect_str)
                    continue
                npc_id = session.companion.id
            else:
                npc_id = EFFECT_NPC_MAP.get(shorthand, shorthand)
            for pid in party_ids:
                current = await resolve_disposition(npc_id, pid, conn=conn, queries_mod=queries, content_mod=content)
                new_disp = shift_disposition(current, delta_str, off_ladder="neutral")
                await mutations.set_npc_disposition(npc_id, pid, new_disp, f"world_effect: {effect_str}", conn=conn)
                if pid == actor_id:
                    pending_events.append(
                        (E.DISPOSITION_CHANGED, {"npc_id": npc_id, "previous": current, "new": new_disp})
                    )
                logger.info("World effect: %s disposition %s → %s", npc_id, current, new_disp)
            continue

        m = _EFFECT_REPUTATION_RE.match(effect_str)
        if m:
            faction_id, event_type = m.group(1), m.group(2)
            faction = await content.get_faction(faction_id)
            if faction is None:
                # Mirror the DM tool adjust_faction_reputation's fail-on-unknown-faction guard.
                # A mistyped faction id in authored on_complete content would otherwise silently
                # write a phantom-faction player_reputation row the real faction never sees.
                # Warn and skip (a content-authoring error) rather than crash the stage tx.
                logger.warning("Unknown faction in reputation world effect: %s", effect_str)
                continue
            try:
                delta = reputation_shift(event_type)
            except ValueError:
                # A typo'd event in authored content: warn and skip rather than crash the
                # whole quest-stage transaction over one bad effect string.
                logger.warning("Unknown reputation event in world effect: %s", effect_str)
                continue
            for pid in party_ids:
                new_value = await reputation_mutations.adjust_player_faction_reputation(
                    pid, faction_id, delta, f"world_effect: {effect_str}", conn=conn
                )
                if pid == actor_id:
                    session.record_event(f"{faction_id} reputation {delta:+d} → {new_value} ({event_type})")
                logger.info("World effect: %s reputation %+d → %s", faction_id, delta, new_value)
            continue

        m = _EFFECT_CORRUPTION_RE.match(effect_str)
        if m:
            delta = int(m.group(1))
            levels_before = pending_corruption if pending_corruption is not None else {}
            previous_levels = {
                pid: levels_before.get(pid, session.member_state(pid).corruption_level) for pid in party_ids
            }
            levels = {pid: max(0, min(3, previous_levels[pid] + delta)) for pid in party_ids}
            if pending_corruption is None:
                for pid, level in levels.items():
                    session.member_state(pid).corruption_level = level
            else:
                pending_corruption.update(levels)
            for pid in party_ids:
                pending_events.append(
                    (
                        E.HOLLOW_CORRUPTION_CHANGED,
                        {
                            "player_id": pid,
                            "level": levels[pid],
                            "previous": previous_levels[pid],
                            "location_id": session.location_id,
                        },
                    )
                )
            logger.info("World effect: corruption %d → %d", previous_levels[actor_id], levels[actor_id])
            continue

        m = _EFFECT_EVENT_RE.match(effect_str)
        if m:
            event_id = m.group(1)
            pending_events.append((E.WORLD_EVENT, {"event_id": event_id}))
            logger.info("World effect: event %s", event_id)
            continue

        m = _EFFECT_MORALE_RE.match(effect_str)
        if m:
            group_name, delta_str = m.group(1), int(m.group(2))
            pending_events.append((E.WORLD_EVENT, {"event_id": f"{group_name}_morale_change", "delta": delta_str}))
            session.record_event(f"{group_name} morale shifted by {delta_str}")
            logger.info("World effect: %s morale %+d (logged, no morale system yet)", group_name, delta_str)
            continue

        logger.warning("Unknown world effect: %s", effect_str)
