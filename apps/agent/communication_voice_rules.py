"""Fictional delivery gates, independent of the player's voice transport."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_data import CombatState

import combat_spatial
import conditions
from condition_sources import DeliveryRefused as DeliveryRefused
from condition_voice_rules import no_spoken_buffs
from spell_voice_rules import is_silenced


class CommunicationKind(StrEnum):
    SPOKEN = "spoken"
    VISUAL = "visual"
    OTHER = "other"


def actor_conditions(state: CombatState | None, actor_id: str, *, rows: dict | None = None) -> list[dict]:
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("Communication requires an identified actor")
    if state is not None:
        actor = state.get_participant(actor_id)
        if actor is None:
            raise ValueError(f"Communication recipient {actor_id!r} is not a combat participant")
        combat_spatial.position(combat_spatial.require_spatial(state), actor_id)
        return conditions.validate_conditions(actor.conditions)
    return conditions.validate_conditions((rows or {}).get(actor_id, {}).get("conditions") or [])


def require_source(state: CombatState | None, speaker_id: str, *, rows: dict | None = None) -> None:
    actor_conditions(state, speaker_id, rows=rows)
    if is_silenced(state, speaker_id):
        raise DeliveryRefused(f"{speaker_id} is silenced and cannot speak")


def can_hear(state: CombatState | None, recipient_id: str, *, rows: dict | None = None) -> bool:
    active = actor_conditions(state, recipient_id, rows=rows)
    return not no_spoken_buffs(active, state=state, actor_id=recipient_id)


def require_delivery(
    kind: CommunicationKind,
    state: CombatState | None,
    speaker_id: str,
    recipient_ids: list[str],
    *,
    rows: dict | None = None,
) -> None:
    try:
        kind = CommunicationKind(kind)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Unknown communication kind {kind!r}") from exc
    # Validate identities and placement before ordinary ineligibility can hide corruption.
    actor_conditions(state, speaker_id, rows=rows)
    for recipient_id in recipient_ids:
        actor_conditions(state, recipient_id, rows=rows)
    if kind is not CommunicationKind.SPOKEN:
        return
    require_source(state, speaker_id, rows=rows)
    for recipient_id in recipient_ids:
        if not can_hear(state, recipient_id, rows=rows):
            raise DeliveryRefused(f"{recipient_id} cannot hear spoken delivery")
