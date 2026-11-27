"""Player ability packet dispatch inside the phase transaction."""

import combat_martial
import combat_reposition
import combat_sacrifice_play
import combat_shadow_step
import veythar_wellspring
import wild_shape
from combat_ability import (
    AbilityCastOutcome,
    _resolve_ability_condition_packet,
    _resolve_ability_packet,
    condition_ability,
)
from combat_ability_gate import (
    EXPLOIT_WEAKNESS,
    MARSHAL_ORDERS,
    REPOSITION,
    SECOND_WIND,
    SHADOW_STEP,
    SMOKE_BOMB,
    VANISH,
    declared_ability,
)
from combat_deescalation import _resolve_deescalation_packet
from combat_order_riders import SACRIFICE_PLAY


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
    player_movement,
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
    if resolved is not None and resolved[0].id == wild_shape.DRUID_ABILITY:
        locked = await queries.get_player(attacker.id, conn=conn, for_update=True)
        if locked is None:
            raise RuntimeError(f"Missing locked player row for Wild Shape: {attacker.id}")
        cost = resolved[0].cost
        form_id, focus, stamina = wild_shape.gate(
            attacker, decl, locked, wild_shape.druid_profile(), focus_cost=cost.focus, stamina_cost=cost.stamina
        )
        beast = await wild_shape.prepare_form(form_id, conn)
        form = await wild_shape.transform(attacker, form_id, beast, focus=focus, stamina=stamina, conn=conn)
        return {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "action": decl.action,
            "wild_shape": form,
        }
    if resolved is not None and resolved[0].id == SACRIFICE_PLAY:
        return await combat_sacrifice_play.resolve(
            session,
            state,
            attacker,
            decl,
            resolved,
            conn=conn,
            sink=sink,
            progress=progress,
            queries=queries,
            mutations=mutations,
            concentration_break_mod=concentration_break_mod,
        )
    if resolved is not None and resolved[0].id == SHADOW_STEP:
        if player_movement is None:
            raise ValueError("Shadow Step requires player movement")
        return await combat_shadow_step.resolve(
            state, attacker, decl, resolved, player_movement, conn=conn, queries=queries
        )
    if resolved is not None and resolved[0].id == VANISH:
        return await combat_martial.vanish(attacker, resolved, conn=conn, queries=queries)
    if resolved is not None and resolved[0].id == SMOKE_BOMB:
        return await combat_martial.smoke_bomb(state, attacker, resolved, conn=conn, queries=queries)
    if resolved is not None and resolved[0].id == SECOND_WIND:
        return await combat_martial.second_wind(
            state, attacker, resolved, conn=conn, queries=queries, mutations=mutations
        )
    if resolved is not None and resolved[0].id == REPOSITION:
        return await combat_reposition.resolve(state, attacker, decl, resolved, conn=conn, queries=queries)
    if resolved is not None and resolved[0].id in MARSHAL_ORDERS:
        return await combat_martial.resolve_order(state, attacker, decl, resolved, conn=conn, queries=queries)
    if resolved is not None and resolved[0].id == EXPLOIT_WEAKNESS:
        return await combat_martial.exploit_weakness(state, attacker, decl, resolved, conn=conn, queries=queries)
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
    summary = await _resolve_ability_packet(
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
    if summary.get("resolved") is True and "wellspring_echo" in summary["cast"]:
        await veythar_wellspring.settle(attacker.id, conn=conn)
        sink.patron_refreshes[attacker.id] = (session.room, session.event_bus)
    return summary
