"""Shared out-of-combat beneficial-condition producer (M4.8 story-007 extraction).

Both the spell cast path (``spell_casting._resolve_cast``) and the ability activation path
(``ability_tools``) land a beneficial condition (blessed/inspired) on a target's
``players.data`` conditions SSOT when cast OUT of combat. This module is the ONE shared
landing helper, unifying the previously-duplicated apply -> persist-on-land -> self-row-reuse
-> non-player-narrate-only logic.

In combat the ``CombatParticipant`` is the SSOT and the declare/resolve phase owns the apply,
so these helpers are only reached on the not-``session.in_combat`` branch.

The mod seams (``queries_mod`` / ``conditions_mod`` / ``conditions_mutations_mod``) stay
injectable so the producer tests can drive the helper with mocked persistence.
"""

import conditions
import db_mutations_conditions
import db_queries


async def apply_beneficial_condition_to_player(
    target_id: str,
    condition: str,
    source: str,
    *,
    caster_row: dict,
    caster_id: str,
    queries_mod=db_queries,
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    conn=None,
) -> bool:
    """Apply + persist one beneficial ``condition`` to one OOC target's ``players.data``.

    Returns whether the buff should be VOICED — True when it landed on a player row, OR when the
    target is a non-player ally (companion/NPC with no ``players.data`` store: narrate-only, no
    write). The write fires ONLY when the condition actually LANDS (``has_condition``) — an immunity
    no-op writes nothing and returns False. A self-target reuses the already-locked ``caster_row``
    instead of re-fetching it.
    """
    if target_id == caster_id:
        target_row = caster_row
    else:
        target_row = await queries_mod.get_player(target_id, conn=conn, for_update=True)
    if target_row is None:
        return True  # non-player target: narrate-only, no players.data write
    new_conditions = conditions_mod.apply_condition(target_row.get("conditions", []), condition, source=source)
    if not conditions_mod.has_condition(new_conditions, condition):
        return False  # immunity / no-op apply — nothing to persist or voice
    await conditions_mutations_mod.save_player_conditions(target_id, new_conditions, conn=conn)
    return True


async def produce_ooc_condition(
    condition: str,
    source: str,
    *,
    target_id: str | None,
    target_ids: list[str] | None,
    caster_row: dict,
    caster_id: str,
    queries_mod=db_queries,
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    conn=None,
) -> list[str]:
    """Resolve the OOC target list and land ``condition`` on each, returning the ids to VOICE.

    Targets are the explicit multi-target list (already deduped + cap-validated upstream), else the
    single ``target_id``, else the caster (self-cast). Each target routes through
    ``apply_beneficial_condition_to_player``; an immunity no-op is skipped. The returned list is the
    subset the DM should name (audio-first per-ally attribution); empty means nothing landed.
    """
    if target_ids:
        cond_target_ids = target_ids
    elif target_id is not None:
        cond_target_ids = [target_id]
    else:
        cond_target_ids = [caster_id]
    voiced: list[str] = []
    for cond_target_id in cond_target_ids:
        landed = await apply_beneficial_condition_to_player(
            cond_target_id,
            condition,
            source,
            caster_row=caster_row,
            caster_id=caster_id,
            queries_mod=queries_mod,
            conditions_mod=conditions_mod,
            conditions_mutations_mod=conditions_mutations_mod,
            conn=conn,
        )
        if landed:
            voiced.append(cond_target_id)
    return voiced
