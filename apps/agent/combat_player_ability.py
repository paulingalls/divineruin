"""Player ability packet dispatch inside the phase transaction."""

import combat_martial
from combat_ability import (
    AbilityCastOutcome,
    _resolve_ability_condition_packet,
    _resolve_ability_packet,
    condition_ability,
)
from combat_ability_gate import MARSHAL_ORDERS, SECOND_WIND, declared_ability
from combat_deescalation import _resolve_deescalation_packet


async def resolve(
    session,
    state,
    attacker,
    decl,
    *,
    conn,
    player,
    sink,
    progress,
    queries,
    cast_resolver,
    cast_outcome,
    mutations,
    resolver,
    concentration_break_mod,
) -> dict:
    if (decl.action or "").lower() == "de_escalate":
        return await _resolve_deescalation_packet(
            session,
            attacker,
            decl,
            state=state,
            conn=conn,
            player=player,
            sink=sink,
            queries=queries,
            progress=progress.scope("deescalation") if progress is not None else None,
        )
    # A non-spell condition ability (M4.8 story-005, e.g. bard_inspire) resolves via the dedicated
    # ability-condition path — deduct its cost and land the condition on the target participant —
    # NOT through _resolve_ability_packet (which casts a spell). Pre-gated in _prevalidate_ability_focus.
    resolved = declared_ability(decl.action)
    if resolved is not None and resolved[0].id == SECOND_WIND:
        return await combat_martial.second_wind(
            state, attacker, resolved, conn=conn, queries=queries, mutations=mutations
        )
    if resolved is not None and resolved[0].id in MARSHAL_ORDERS:
        return await combat_martial.narrated_order(attacker, decl, resolved, conn=conn, queries=queries)
    cond_ability = condition_ability(resolved)
    if cond_ability is not None:
        return await _resolve_ability_condition_packet(
            session,
            attacker,
            decl,
            cond_ability,
            state=state,
            conn=conn,
            player=player,
            queries=queries,
            progress=progress,
        )
    return await _resolve_ability_packet(
        session,
        attacker,
        decl,
        state=state,
        cast_resolver=cast_resolver,
        conn=conn,
        player=player,
        cast_outcome=cast_outcome if cast_outcome is not None else AbilityCastOutcome(),
        progress=progress,
        damage_deps={
            "mutations": mutations,
            "queries": queries,
            "resolver": resolver,
            "concentration_break_mod": concentration_break_mod,
            "sink": sink,
        },
    )
