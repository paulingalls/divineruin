"""Build the HP_CHANGED payload from a player row or combat participant."""

from __future__ import annotations

from typing import TYPE_CHECKING

import temp_hp
from patron_passives import effective_hp

if TYPE_CHECKING:
    from combat_participant import CombatParticipant


def from_player(player: dict, *, current: int | None = None, temporary: int | None = None) -> dict[str, int]:
    hp = effective_hp(player)
    # Heal receipts carry the committed current because the locked row still has its old value.
    return {
        "current": hp["current"] if current is None else current,
        "max": hp["max"],
        "temp_hp": temp_hp.from_player(player) if temporary is None else temp_hp.validate(temporary),
    }


def from_participant(participant: CombatParticipant, *, settled_hp: tuple[int, int] | None = None) -> dict[str, int]:
    current, maximum = settled_hp if settled_hp is not None else (participant.hp_current, participant.hp_max)
    return {"current": current, "max": maximum, "temp_hp": participant.temp_hp}
