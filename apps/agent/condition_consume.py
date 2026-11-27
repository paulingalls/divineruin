"""Persist bonus consumption without adopting an uncommitted combat snapshot."""

import asyncpg

import db
import db_mutations_conditions
from condition_catalog import GUIDING_LIGHT_MARK


async def consume_beneficial_conditions(
    player_id: str,
    consumed: tuple[str, ...],
    conditions_mutations=db_mutations_conditions,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    combat_state=None,
    db_mod=db,
):
    """The caller adopts the returned snapshot only after its transaction commits.

    Server-side row removal preserves unrelated concurrent condition writes.
    """
    if not consumed:
        return
    if combat_state is not None and conn is None:
        async with db_mod.transaction() as transaction_conn:
            return await consume_beneficial_conditions(
                player_id,
                consumed,
                conditions_mutations,
                conn=transaction_conn,
                combat_state=combat_state,
                db_mod=db_mod,
            )
    await conditions_mutations.remove_player_conditions(player_id, consumed, conn=conn)
    return await persist_combat_consumption(combat_state, player_id, consumed, conn=conn)


async def persist_combat_consumption(state, player_id, consumed, *, conn):
    if state is None or not consumed:
        return None
    from copy import deepcopy

    import conditions
    import db_mutations

    updated = deepcopy(state)
    participant = updated.get_participant(player_id)
    if participant is None:
        raise ValueError(f"Cannot consume combat conditions for unknown actor {player_id!r}")
    participant.conditions = conditions.remove_conditions(participant.conditions, consumed)
    await db_mutations.save_combat_state(updated.combat_id, updated.to_dict(), conn=conn)
    return updated


def expire_guiding_light(state, caster_id: str | None) -> None:
    for participant in state.participants:
        participant.conditions = [
            condition
            for condition in participant.conditions
            if not (
                condition["type"] == GUIDING_LIGHT_MARK
                and condition["originating_participant_id"] == caster_id
                and condition["inflicted_round"] < state.round_number
            )
        ]


def serialize_combat_check(function):
    from functools import wraps

    @wraps(function)
    async def serialized(context, *args, **kwargs):
        session = context.userdata
        async with session.combat_state_lock:
            return await function(context, *args, **kwargs)

    return serialized
