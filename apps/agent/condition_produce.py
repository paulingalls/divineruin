"""Shared out-of-combat beneficial-condition producer (M4.8 story-007).

Both the spell cast path (``spell_casting._resolve_cast``) and the ability activation path
(``ability_tools``) land a beneficial condition (blessed/inspired) on a target's
``players.data`` conditions SSOT when cast OUT of combat. This module is the ONE shared
landing helper.

Every target must be a PARTY-GATED player (a member of the caster's party, ``players.data``
SSOT) or the caster's own present companion (narrate-only allowlist — a companion has no
``players.data`` row, so it can never be a write target). A target that is neither a non-party
PC nor a phantom id is refused fail-loud (``ValueError``, no write); a party id absent from
``players`` also fails loud (debts d2316e2f74af / non-existent target). Party targets are
fetched and written in ONE id-ordered batch each (debt b0207c768743 — was N round-trips); the
caster reuses the already-locked ``caster_row`` (self-row-reuse + the deadlock-safe union
lock order below — NOT caster-first, see ``lock_ooc_caster_and_targets``, story-005/story-008).

In combat the ``CombatParticipant`` is the SSOT and the declare/resolve phase owns the apply,
so this helper is only reached on the not-``session.in_combat`` branch.

The mod seams (``queries_mod`` / ``conditions_mod`` / ``conditions_mutations_mod``) stay
injectable so the producer tests can drive the helper with mocked persistence.
"""

from livekit.agents.llm import ToolError

import conditions
import db_mutations_conditions
import db_queries


def resolve_effective_targets(
    target_ids: list[str] | None, target_id: str | None, *, self_value, dedup: bool = False
) -> list:
    """The effective target list: ``target_ids`` when given, else ``[target_id]``, else
    ``[self_value]`` (self-cast). ``dedup`` order-preserving-dedups ``target_ids`` (the in-combat
    caller's contract); the OOC callers pass their already-normalized list and dedup=False."""
    if target_ids:
        return list(dict.fromkeys(target_ids)) if dedup else target_ids
    if target_id is not None:
        return [target_id]
    return [self_value]


async def lock_ooc_caster_and_targets(
    *,
    produces_ooc: bool,
    player_id: str,
    target_id: str | None,
    target_ids: list[str] | None,
    party_member_ids: list[str],
    queries_mod=db_queries,
    conn=None,
) -> tuple[dict, dict]:
    """Acquire the deadlock-safe pre-lock for an OOC condition-producing caster (story-005/008).

    Locks the {caster} UNION {non-caster party targets} in ONE ascending-player_id
    ``get_players_for_update`` batch — NEVER caster-first (that ordering is debt 361417d1bea5,
    the deadlock this union lock replaced). ``produces_ooc`` is the caller's own predicate (a
    condition-producing spell/ability, out of combat); when False no targets are pre-locked
    (still locks just the caster). Returns ``(locked_rows, caster_row)``; raises ``ToolError``
    if the caster row doesn't exist."""
    ooc_targets = (target_ids or ([target_id] if target_id else [])) if produces_ooc else []
    lock_ids = sorted({player_id} | {t for t in ooc_targets if t in party_member_ids})
    locked_rows = await queries_mod.get_players_for_update(lock_ids, conn=conn)
    player = locked_rows.get(player_id)
    if player is None:
        raise ToolError(f"Unknown player: {player_id}")
    return locked_rows, player


async def produce_ooc_condition(
    condition: str,
    source: str,
    *,
    target_id: str | None,
    target_ids: list[str] | None,
    caster_row: dict,
    caster_id: str,
    party_member_ids: list[str],
    companion_id: str | None,
    queries_mod=db_queries,
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    locked_rows: dict[str, dict] | None = None,
    conn=None,
) -> list[str]:
    """Resolve the OOC target list, party-gate each target, and batch-land ``condition``.

    Targets are the explicit multi-target list (already deduped + cap-validated upstream), else the
    single ``target_id``, else the caster (self-cast). Each target must be in ``party_member_ids``
    (a player-row write target) or equal to ``companion_id`` (narrate-only, no write) — anything else
    raises ``ValueError``. Non-caster party targets are fetched + locked in ONE id-sorted
    ``get_players_for_update`` batch; a requested party id missing from the result also raises
    ``ValueError`` (non-existent). The condition is applied per-row and only rows where it actually
    LANDS (``has_condition`` — an immunity no-op writes nothing) are collected into ONE batched
    ``save_many_player_conditions`` write. Returns the ids to VOICE, in target order (audio-first
    per-ally attribution).
    """
    cond_target_ids = resolve_effective_targets(target_ids, target_id, self_value=caster_id)

    party = set(party_member_ids)
    for tid in cond_target_ids:
        if tid not in party and tid != companion_id:
            raise ValueError(f"{tid} is not a party member or the caster's companion — refusing {condition}")

    non_caster_ids = sorted({tid for tid in cond_target_ids if tid in party and tid != caster_id})
    if locked_rows is not None:
        fetched = {tid: locked_rows[tid] for tid in non_caster_ids if tid in locked_rows}
    else:
        fetched = await queries_mod.get_players_for_update(non_caster_ids, conn=conn) if non_caster_ids else {}
    missing = [tid for tid in non_caster_ids if tid not in fetched]
    if missing:
        raise ValueError(f"Party member(s) not found: {', '.join(missing)}")

    rows_by_id = dict(fetched)
    rows_by_id[caster_id] = caster_row

    writes: dict[str, list[dict]] = {}
    voiced: list[str] = []
    for tid in cond_target_ids:
        if companion_id is not None and tid == companion_id:
            voiced.append(tid)  # narrate-only ally: no players.data row, no write
            continue
        row = rows_by_id[tid]
        new_conditions = conditions_mod.apply_condition(row.get("conditions", []), condition, source=source)
        if not conditions_mod.has_condition(new_conditions, condition):
            continue  # immunity / no-op apply — nothing to persist or voice
        writes[tid] = new_conditions
        voiced.append(tid)

    if writes:
        await conditions_mutations_mod.save_many_player_conditions(writes, conn=conn)

    return voiced
