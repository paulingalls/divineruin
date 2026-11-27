"""Combat declaration, resolution and legendary-action tool entry points."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import choir_encounter
import combat_cunning_action
import combat_item_rider
import combat_martial
import combat_phase
import combat_quick_fingers
import combat_spatial
import combat_spatial_declarations
import concealment
import db_mutations
import db_queries
import declaration_payloads
import item_heal
import patron_synergy_combat
import patron_synergy_heal
import spell_condition_cleanse
import still_encounter
from combat_resolve_phase import _resolve_phase_locked
from combat_support import _participant_roster, _require_combat
from db_errors import db_tool
from declaration_payloads import DeclPayload
from reshape_payloads import ReshapeSelection
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def declare_phase(
    context: RunContext[SessionData],
    declarations: list[DeclPayload],
) -> str:
    """Open a combat phase by recording every combatant's declared action for this
    round, then call resolve_phase to resolve them. Pass one declaration per acting
    combatant, each naming its actor_id and picked by its kind: attack, ability,
    ability_move, interact, consume, attack_consume, maneuver, move, reposition, defend, retreat or yield.
    To surrender, declare {"kind":"yield","actor_id":"<player or companion id>"}.
    This spends their action. Yield ends when they act against a hostile or when combat ends.
    For a potion, salve or berry,
    declare consume with the holder's actor_id and the queried item_id. Set target_id
    to the ally receiving it or an empty string for the holder. Move names an explicit destination in feet and consumes
    this phase action, limited to the actor's persisted speed. A Nythera skirmisher or rogue can
    opt in to Unmoored Step once per encounter with nythera_step=true. The move follows normal
    movement rules and provokes no opportunity attacks. It spends the step when it resolves.
    Set nythera_step=false for ordinary moves. Only the Architect may include
    Reshape operations, on an attack, move or defend. The sections resolve before the action.
    Use the Architect's live wall ids and remaining Reshape uses from the combat facts.
    Shadow Step uses ability_move with action rogue_shadow_step or its active variant id and a destination
    from combat facts. Move up to effective speed using normal movement rules. End within 5 feet of the
    nearest point on a wall segment or of a standing structure, or inside smoke. No opportunity attacks
    are provoked, and the rogue finishes concealed.
    Second Wind is an ability with empty targets. Rallying Shout names one standing ally.
    Marshal orders name standing allies other than the marshal. For Reposition, use kind="reposition",
    actor_id for the marshal, target_id for the ally, and destination in feet within 15 feet of the ally.
    Use ability declarations for marshal_direct_strike with [ally, foe], marshal_coordinated_assault
    with two distinct allies in the requested order, and marshal_sacrifice_play with one ally.
    Declare marshal_field_medic_order on one player ally. Once granted, before the end of the
    following round, that ally can declare attack_consume with an equipped weapon name, attack target_id,
    healing item_id, and heal_target_id (empty for the holder). An ordinary attack leaves the order pending.
    Devastating Strike is an ability naming one foe. For Shield Bash, declare a melee weapon attack
    with rider="shield_bash". A rogue can set rider="dash" for double approach movement
    or rider="hide" to attempt Stealth after the attack. Use rider="disengage" to avoid enemy opportunity
    attacks during the declaration. Quick Fingers uses rider="quick_fingers" on a melee attack against a standing foe.
    Choose steal, plant or swap in quick_fingers_mode. For plant or swap, copy quick_fingers_item from the rogue's inventory query.
    Leave the item empty for steal. Use empty rider, quick_fingers_mode and quick_fingers_item for ordinary attacks.
    Include the player, every
    conscious companion, and every enemy that acts this phase — one declaration each.
    In Wild Shape, choose a natural attack from the latest participants[].actions
    or executable_actions. Use action="" for the first one. Equipped weapons are unavailable.
    Call this once per round at the declaration beat; resolve_phase resolves and
    narrates the whole phase in initiative order."""
    try:
        engine_declarations = declaration_payloads.to_engine_declarations(declarations)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return await _declare_phase_impl(context, engine_declarations)


async def _declare_phase_impl(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
    *,
    mutations=db_mutations,
    queries=db_queries,
) -> str:
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _declare_phase_locked(context, declarations, mutations=mutations, queries=queries)


async def _declare_phase_locked(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
    *,
    mutations=db_mutations,
    queries=db_queries,
) -> str:
    logger.info("declare_phase called: %d declarations", len(declarations or {}))
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.legendary_continuation is not None:
        raise ToolError("Call resolve_phase to finish the legendary action before declaring.")
    if cs.beat != combat_phase.PhaseBeat.DECLARATION:
        raise ToolError(f"Not at the declaration beat (current beat: {cs.beat}). Call resolve_phase first.")

    # The pure engine records the declarations and advances DECLARATION -> RESOLUTION.
    # An empty declarations payload is a ValueError from the engine — surface it as a
    # ToolError so the DM re-prompts rather than crashing combat.
    try:
        combat_spatial_declarations.preflight_state(cs)
        declarations = declarations.copy()
        for actor in cs.participants:
            if actor.wild_shape is None or (decl := declarations.get(actor.id)) is None:
                continue
            if decl.get("type") == "attack" and decl.get("action") == "" and "healing_item" not in decl:
                declarations[actor.id] = {**decl, "action": actor.action_pool[0]["name"]}
        concealed = (
            await concealment.concealed_ids(cs, queries=queries)
            if any(not p.is_ally and p.id in declarations for p in cs.participants)
            else frozenset()
        )
        next_state, _adv = combat_phase.advance_combat_phase(cs, declarations=declarations, concealed=concealed)
        await combat_cunning_action.preflight(next_state, queries=queries)
        await combat_quick_fingers.preflight(next_state, queries=queries)
        await combat_martial.preflight_orders(next_state, queries=queries)
        await patron_synergy_combat.preflight_tidal_step(next_state, get_player=queries.get_player)
        await patron_synergy_heal.preflight_inspire_heal(next_state, get_player=queries.get_player)
        await combat_item_rider.preflight(session, next_state)
        await item_heal.preflight_declarations(session, next_state)
        await spell_condition_cleanse.preflight_declarations(session, next_state, queries=queries)
        choir_facts = await choir_encounter.facts(next_state, queries=queries)
    except ValueError as e:
        raise ToolError(str(e)) from e

    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())
    session.combat_state = next_state

    response = {
        "spatial": combat_spatial.response_facts(next_state, session.acting_player_id, session.primary_player_id),
        "beat": next_state.beat,
        "round": next_state.round_number,
        "choir": choir_facts,
        "still": still_encounter.facts(next_state),
        "participants": _participant_roster(next_state.participants),
        "accepted_actors": list(next_state.pending_declarations.keys()),
    }
    logger.info("declare_phase result: beat=%s, actors=%s", next_state.beat, response["accepted_actors"])
    return json.dumps(response)


@function_tool()
@db_tool
async def resolve_phase(
    context: RunContext[SessionData],
) -> str | tuple:
    """Resolve the combat phase declared by declare_phase. Drives the deterministic
    engine: resolves every declared attack in initiative order against the
    combatants' HP, narrates the outcomes (you supply the prose from the returned
    packets), then wraps the phase — Resonance decays, death saves come due, and if
    every enemy has fallen (or the player has died) combat ends and hands back to the
    exploration agent. Call this once, right after declare_phase. The response lists
    per-actor resolution packets to narrate plus any death saves the player owes.
    Voice regeneration that restores HP in a packet's turn_start_effects.
    The ``exhaustion_narration`` map (participant ID -> flavor line) gives the
    weariness cue to weave into the narration for any actor carrying Exhausted stacks."""
    return await _resolve_phase_impl(context)


async def _resolve_phase_impl(context: RunContext[SessionData], **di) -> str | tuple:
    """Serialise the phase against the other path that can end this fight (end_combat).

    Both take `combat_state` as their only re-entry guard and can only release it after their
    transaction commits, so overlapping calls would otherwise both pass `_require_combat` and grant
    the encounter's rewards twice. Holding the session's combat-state lock across the whole call means
    a waiter re-reads `combat_state` after the holder cleared it and gets "Not in combat" — the
    truth — instead of a second payout. See SessionData.combat_state_lock.
    """
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _resolve_phase_locked(context, **di)


@function_tool()
@db_tool
async def consume_legendary_action(
    context: RunContext[SessionData],
    boss_id: str,
    action_id: str,
    target_id: str,
    reshape: list[ReshapeSelection],
) -> str:
    """Spend and execute an action listed in the encounter's legendary options.
    Use the actor's id and exact action id at declaration or after the allies act.
    An attack takes a target and empty reshape. Shift Wall takes an empty target and
    one move_wall operation. Reshape takes an empty target and one operation.
    Narrate the returned packets. Honor reaction and Fate offers and resume with
    resolve_phase. For a legacy Boss, send empty action and target ids and an empty list
    to spend its single point before narrating the extra beat."""
    return await _consume_legendary_action_impl(
        context,
        boss_id,
        action_id=action_id,
        target_id=target_id,
        reshape=tuple(operation.model_dump() for operation in reshape),
    )


async def _consume_legendary_action_impl(
    context: RunContext[SessionData],
    boss_id: str,
    *,
    action_id: str = "",
    target_id: str = "",
    reshape: tuple[dict, ...] = (),
    mutations=db_mutations,
    queries=db_queries,
) -> str:
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _consume_legendary_action_locked(
            context,
            boss_id,
            action_id=action_id,
            target_id=target_id,
            reshape=reshape,
            mutations=mutations,
            queries=queries,
        )


async def _consume_legendary_action_locked(
    context: RunContext[SessionData],
    boss_id: str,
    *,
    action_id: str,
    target_id: str,
    reshape: tuple[dict, ...],
    mutations,
    queries,
) -> str:
    session: SessionData = context.userdata
    cs = _require_combat(session)
    if cs.wrap_continuation is not None:
        raise ToolError("Call resolve_phase to finish the round before spending a legendary action.")
    if cs.legendary_continuation is not None or session.fate_offer is not None:
        raise ToolError("Finish the held roll or action before spending a legendary action.")
    try:
        concealed = await concealment.concealed_ids(cs, queries=queries) if target_id else frozenset()
        next_state = combat_phase.consume_legendary_action(
            cs, boss_id, action_id=action_id, target_id=target_id, reshape=reshape, concealed=concealed
        )
    except ValueError as e:
        raise ToolError(str(e)) from e

    if next_state.legendary_continuation is not None:
        response = await _resolve_phase_locked(context, legendary_start=next_state, mutations=mutations)
        assert isinstance(response, str)
        return response
    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())
    session.combat_state = next_state
    boss = next_state.get_participant(boss_id)
    assert boss is not None
    return json.dumps({"actor_id": boss_id, "legendary_actions_remaining": boss.legendary_actions})
