"""Deterministic world effects declared by a quest stage."""

import logging
import re

import asyncpg
from livekit.agents.llm import ToolError

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
_EFFECT_REPUTATION_RE = re.compile(r"^(\w+)_reputation\s+(\w+)$")


def decision_option(condition: dict, option_id: str | None) -> dict | None:
    if condition.get("type") != "decision_made":
        if option_id is not None:
            raise ToolError("This stage is not a decision; omit option_id.")
        return None
    options = condition["options"]
    if option_id not in options:
        raise ToolError(f"Choose option_id for {condition['decision']}. Valid options: {', '.join(options)}.")
    return options[option_id]


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
    party_ids: tuple[str, ...] | None = None,
    pending_notes: list[str] | None = None,
    actor_id: str | None = None,
) -> None:
    """Parse and apply deterministic world_effects from quest on_complete."""
    record_note = session.record_event if pending_notes is None else pending_notes.append
    actor_id = actor_id if actor_id is not None else session.acting_player_id
    party_ids = party_ids if party_ids is not None else tuple(session.party.member_ids)
    for effect_str in effects:
        if effect_str.startswith("set_flag:"):
            parts = effect_str.split(":")
            if len(parts) != 3 or not re.fullmatch(r"\w+", parts[1]) or not parts[2].strip():
                raise ValueError(f"Malformed flag effect: {effect_str}")
            raw = parts[2]
            value = {"true": True, "false": False}.get(raw)
            if value is None:
                value = int(raw) if re.fullmatch(r"-?\d+", raw) else raw
            for pid in party_ids:
                await mutations.set_player_flag(pid, parts[1], value, conn=conn)
            continue
        m = _EFFECT_DISPOSITION_RE.match(effect_str)
        if m:
            shorthand, delta_str = m.group(1), int(m.group(2))
            if shorthand == COMPANION_SHORTHAND:
                if session.companion is None:
                    raise ToolError("This effect requires a bound companion.")
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
                raise ValueError(f"Unknown faction in world effect: {effect_str}")
            try:
                delta = reputation_shift(event_type)
            except ValueError as exc:
                raise ValueError(f"Unknown reputation world effect: {effect_str}") from exc
            for pid in party_ids:
                new_value = await reputation_mutations.adjust_player_faction_reputation(
                    pid, faction_id, delta, f"world_effect: {effect_str}", conn=conn
                )
                if pid == actor_id:
                    record_note(f"{faction_id} reputation {delta:+d} → {new_value} ({event_type})")
                logger.info("World effect: %s reputation %+d → %s", faction_id, delta, new_value)
            continue

        if effect_str == "event:god_whisper:player_patron":
            pending_events.append((E.WORLD_EVENT, {"event_id": "god_whisper:player_patron"}))
            continue

        raise ValueError(f"Unknown world effect: {effect_str}")
