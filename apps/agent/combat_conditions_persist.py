"""Cross-encounter condition persistence for combat teardown.

Combat's condition set is split by lifetime: phase-scoped instances (Prone/Stunned/…) die with the
combat row, while persists_across_encounters ones (Wounded/Exhausted/Hollowed) and surviving
beneficial dice have to land back in each member's own players.data row. That reconciliation is a
self-contained concern with its own merge rules, so it lives here rather than in combat_end.
"""

import json

import conditions
import db_mutations_conditions


def _merge_persistent_conditions(existing: list[dict], acquired: list[dict]) -> list[dict]:
    """Union the player's stored cross-encounter conditions with those acquired this fight.

    Combat only ACCRUES (rest clears, a later milestone), so a fight never drops a pre-existing
    condition. On a type conflict, keep the instance with the higher accrual — more ``stacks``
    (Exhausted), or higher ``stage`` (Hollowed) — so a fight that deepens an already-persisted
    Exhausted isn't silently discarded. combat-START load (M4.4 story-005, combat_init) now carries
    the prior store onto the participant, so a combat-gained instance already folds in the prior
    accrual; max() stays the safe floor guarding against ever regressing to the lesser of the two."""

    def _severity(c: dict) -> int:
        return c.get("stacks", c.get("stage", 1))

    merged = {c["type"]: c for c in existing}
    for c in acquired:
        prior = merged.get(c["type"])
        if prior is None or _severity(c) > _severity(prior):
            merged[c["type"]] = c
    return list(merged.values())


def _conditions_changed(before: list[dict], after: list[dict]) -> bool:
    """True when two condition lists differ as multisets (order-independent). Guards the combat-end
    writeback from a redundant DB write when a reconciliation leaves the stored set unchanged."""

    def _key(conds: list[dict]) -> list[str]:
        return sorted(json.dumps(c, sort_keys=True) for c in conds)

    return _key(before) != _key(after)


async def reconcile_member_conditions(player_part, *, conn) -> None:
    """Reconcile one player participant's cross-encounter conditions + beneficial dice into THEIR
    own players.data row (keyed on ``player_part.id`` == that member's player_id).

    The persists_across_encounters conditions acquired this fight (Wounded/Exhausted/Hollowed)
    MERGE into the member's store; phase-scoped ones (Prone/Stunned/…) drop with the combat row.
    Combat only ACCRUES persistent conditions (rest clears them, a later milestone), so we union
    with the existing store rather than overwrite — else a fight would clobber a pre-combat Wounded.

    Beneficial OOC dice (Blessed/Inspired) load from the store onto the participant at combat-start
    (combat_init, M4.4 story-005) and are consumed-on-use, so the participant's FINAL set is
    authoritative — a die spent in combat must be dropped post-combat, and one granted mid-combat
    that survives must persist (concern ab37d4fc61c6). Keyed on bonus_die (the only consumed-on-use
    character buffs); phase-scoped combat conditions carry no bonus_die and correctly stay dropped.
    Broader OOC-condition reconciliation (Poisoned/Charmed) waits on an in-combat applier (M13).

    Runs inside the caller's end transaction. The read runs every combat end (a consumed buff leaves
    no trace on the participant), but a change-gate skips the write when nothing moved."""
    acquired = [c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].persists_across_encounters]
    surviving_buffs = [
        c for c in player_part.conditions if conditions.CONDITION_CATALOG[c["type"]].bonus_die is not None
    ]
    existing = await db_mutations_conditions.read_player_conditions(player_part.id, conn=conn)
    existing_non_buff = [c for c in existing if conditions.CONDITION_CATALOG[c["type"]].bonus_die is None]
    reconciled = _merge_persistent_conditions(existing_non_buff, acquired) + surviving_buffs
    if _conditions_changed(existing, reconciled):
        await db_mutations_conditions.save_player_conditions(player_part.id, reconciled, conn=conn)
