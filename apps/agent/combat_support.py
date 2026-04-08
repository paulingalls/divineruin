"""Shared helpers for combat tool modules."""

import json
import logging

import combat_resolution
import event_types as E
from game_events import publish_game_event
from session_data import CombatParticipant, CombatState, SessionData

logger = logging.getLogger("divineruin.tools")


def _participant_summary(p: CombatParticipant) -> dict:
    """Serialize a participant for LLM response (no internal state like HP numbers)."""
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "initiative": p.initiative,
        "hp_status": combat_resolution.hp_threshold_status(p.hp_current, p.hp_max),
        "ac": p.ac,
        "is_fallen": p.is_fallen,
    }


def _require_combat(session: SessionData) -> tuple[CombatState, str | None]:
    """Return (combat_state, None) if in combat, or (None, error_json) if not."""
    if session.combat_state is None:
        return None, json.dumps({"error": "Not in combat."})  # type: ignore[return-value]
    return session.combat_state, None


async def _publish_sounds(session: SessionData, sounds: list[str]) -> None:
    """Publish multiple sound events."""
    for sound in sounds:
        await publish_game_event(
            session.room,
            E.PLAY_SOUND,
            {"sound_name": sound},
            event_bus=session.event_bus,
        )
