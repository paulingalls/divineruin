"""Deity definitions for character creation. Audio-first descriptions.

Roster is sourced from `content/gods.json` per ADR 0001.
The Unbound Path (`id="none"`) is synthesized here because it is the absence
of a patron, not one of them, and does not seed the `god_agent_state` table.
"""

from __future__ import annotations

from dataclasses import dataclass

from _gods_content import load_gods

UNBOUND_ID = "none"
MORTAEN_ID = "mortaen"


def patron_death_save_bonus(patron_id: str) -> int:
    """The flat death-save bonus granted by a patron (M4.4 §M4.4 — Mortaen's faithful get +2).

    Stub until the Phase-8 patron-modifier system; reads only ``patron_id`` so the Phase-8
    rework can replace it without touching callers."""
    return 2 if patron_id == MORTAEN_ID else 0


def patron_waives_first_death(patron_id: str, prior_death_count: int) -> bool:
    """Whether the patron waives this death entirely (M4.4 — a Mortaen patron's first-ever
    death is free: not recorded, not counted, no cost, and skips the Mortaen meeting).

    ``prior_death_count`` is the permanent death count BEFORE this death. Only a Mortaen
    patron with no prior deaths qualifies; the second death onward is counted normally.
    Stub until the Phase-8 patron-modifier system."""
    return patron_id == MORTAEN_ID and prior_death_count == 0


@dataclass(frozen=True)
class DeityData:
    id: str
    name: str
    title: str  # e.g. "the Radiant Blade"
    domain: str
    description: str  # Audio-first personality sketch
    card_description: str
    synergy_classes: tuple[str, ...]


_UNBOUND = DeityData(
    id=UNBOUND_ID,
    name="No Patron",
    title="the Unsworn",
    domain="Independence",
    description=(
        "You walk without a god's hand on your shoulder. Some call it foolish in times like "
        "these. Others call it honest. The gods have their own agendas — you'd rather "
        "keep yours clear."
    ),
    card_description="No divine patron. Walk your own path, free of divine obligation.",
    synergy_classes=(),
)


def _load_deities() -> dict[str, DeityData]:
    entries = load_gods()
    for entry in entries:
        if entry["god_id"] == UNBOUND_ID:
            raise ValueError(
                f"content/gods.json must not contain god_id={UNBOUND_ID!r} — Unbound "
                "is synthesized in creation_deities and must not seed god_agent_state "
                "(see ADR 0001)"
            )
    deities: dict[str, DeityData] = {
        entry["god_id"]: DeityData(
            id=entry["god_id"],
            name=entry["short_name"],
            title=entry["title"],
            domain=entry["domain"],
            description=entry["description"],
            card_description=entry["card_description"],
            synergy_classes=tuple(entry["synergy_classes"]),
        )
        for entry in entries
    }
    deities[UNBOUND_ID] = _UNBOUND
    return deities


DEITIES: dict[str, DeityData] = _load_deities()
