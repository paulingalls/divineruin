"""Faction reputation rules engine (story-002, M23) — pure, no IO, no RNG.

A player's standing with a faction is a single integer `player_reputation.data["value"]`
(read by db_queries.get_player_faction_reputation, gated by encounter_stance against a
faction's reputation_tiers). This module owns the deterministic magnitude of a reputation
change: a named world event -> a fixed integer delta, the direct analogue of
social_resolution.disposition_shift (LLM/engine decides *which* event fired; the rules own
*how much*, per CLAUDE.md golden rule #3). The delta table is a code constant, not
DB-loaded content — same closed-table discipline as veil_ward.WARD_SOURCES and
social_resolution.DISPOSITION_SHIFT.

The DM tool (reputation_tools), the quest-completion trigger (quest_tools), and the combat
kill + de-escalation triggers (both in combat_end, gated on the victory/deescalated outcome
for write atomicity) all route their magnitude through reputation_shift, so the event->delta
contract lives in exactly one place. The db_mutations_reputation writer applies the returned
delta to the stored value.
"""

# Named reputation event -> fixed delta. Gains are small and positive, penalties negative;
# faction tier thresholds (content/factions.json) run -10 (hostile) .. +25 (honored), so a
# completed quest (+5) is one friendly step and repeated kills accrue toward hostility.
REPUTATION_EVENTS: dict[str, int] = {
    "completed_faction_quest": 5,
    "aided_faction": 2,
    "deescalated_faction": 3,
    "attacked_faction": -2,
    "killed_faction_member": -3,
    "betrayed_faction": -5,
}


def reputation_shift(event_type: str) -> int:
    """Return the reputation delta for a named `event_type`. Fail loud off the table.

    Raises ValueError for an event not in REPUTATION_EVENTS rather than silently returning
    0 — an unknown event is a caller/content bug, and a silent no-op would leave the DM
    narrating a reputation change that never persisted.
    """
    try:
        return REPUTATION_EVENTS[event_type]
    except KeyError:
        raise ValueError(
            f"unknown reputation event {event_type!r}; expected one of {sorted(REPUTATION_EVENTS)}"
        ) from None
