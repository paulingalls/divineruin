"""The round's one reaction: whether it is spent, and what it was spent ON (M29, story-017).

``CombatState.reactions_available`` was ``dict[str, bool]``: True unspent, False spent, key absent
= no budget. That said a reaction FIRED but not which one, nor against which held enemy action —
and story-018's outcomes both need exactly that ("halve THIS damage", "+2 AC against THIS
attack"). This module owns the record that replaces the bool, and the read/write of it.

JSONB-native plain dicts, like ``held_actions`` and ``open_window``, so the field round-trips
through ``CombatState.to_dict``/``from_dict`` with no nested rebuild. The shape is UNIFORM — an
unspent entry carries the same keys as a spent one, all None — so a reader never branches on which
keys exist. ``stage`` is carried rather than parsed back out of ``window_id``: an id string is a
display token, and splitting ``"r1-0-post_roll"`` would make its format a load-bearing contract.

It lives outside session_data.py, which is at 453 of the 500-line cap, and imports nothing from it
(no cycle): combat_phase, combat_hold and session_data.from_dict all read the shape from here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("divineruin.tools")


def unspent() -> dict:
    """The round's reaction, granted and not yet used."""
    return {"spent": False, "ability_id": None, "window_id": None, "stage": None, "held_seq": None}


def spend(ability_id: str, window: dict, *, held_seq: int) -> dict:
    """The binding: WHICH reaction answered WHICH held action, at which stage of its blow.

    ``held_seq`` + ``stage`` are what story-018 matches a held action on — the window id alone
    would force it to parse the id, and the ability id alone would not say which blow.
    """
    return {
        "spent": True,
        "ability_id": ability_id,
        "window_id": window["id"],
        "stage": window.get("stage"),
        "held_seq": held_seq,
    }


def is_spent(entry: dict | None) -> bool:
    """Has this actor used their reaction? An ABSENT entry is no budget at all, not an unspent one.

    Read this rather than the entry's truthiness: a spend record is a truthy object, so a
    boolean test on it reports every spent reaction as still available — which would leave
    combat_hold.pause_allowed holding the beat open for a player who has nothing left to spend.
    """
    if entry is None:
        return True
    return bool(entry["spent"])


def normalize(raw: dict) -> dict:
    """Upgrade a ``reactions_available`` map loaded from JSONB to the record shape.

    Every combat_instances row written before story-017 stores ``dict[str, bool]``, on the exact
    field story-018 reads to choose which blow a reaction modifies — and ``from_dict`` restored it
    as a raw passthrough, so those bools would reach ``entry["spent"]`` and TypeError mid-fight.

    It normalizes rather than raising, which bends constraint 4 deliberately: failing loud would
    kill an in-flight combat on deploy over a row that is not WRONG, only older. True meant
    AVAILABLE, so it becomes an unspent record; False meant SPENT, and "spent, no binding" is the
    honest reading of a bare bool — story-018 applies no modifier for it. Logged once per load,
    not per entry.
    """
    upgraded: dict[str, dict] = {}
    legacy: list[str] = []
    for actor_id, entry in raw.items():
        if isinstance(entry, bool):
            legacy.append(actor_id)
            upgraded[actor_id] = unspent() if entry else {**unspent(), "spent": True}
        else:
            upgraded[actor_id] = entry
    if legacy:
        logger.info(
            "upgraded %d pre-story-017 reaction entries to the spend-record shape (%s); "
            "a spent one carries no binding, so no reaction modifier applies to it",
            len(legacy),
            ", ".join(sorted(legacy)),
        )
    return upgraded
