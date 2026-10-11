"""Combat declaration, resolution and legendary-action tool entry points."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import choir_encounter
import combat_item_rider
import combat_phase
import combat_spatial
import combat_spatial_declarations
import db_mutations
import declaration_payloads
from combat_resolve_phase import _resolve_phase_locked
from combat_support import _participant_roster, _require_combat
from db_errors import db_tool
from declaration_payloads import DeclPayload
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
    interact, maneuver, move, defend or retreat. Move names an explicit destination in feet and consumes
    this phase action, limited to the actor's persisted speed. Include the player, every
    conscious companion, and every enemy that acts this phase — one declaration each.
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
) -> str:
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _declare_phase_locked(context, declarations, mutations=mutations)


async def _declare_phase_locked(
    context: RunContext[SessionData],
    declarations: dict[str, dict],
    *,
    mutations=db_mutations,
) -> str:
    logger.info("declare_phase called: %d declarations", len(declarations or {}))
    session: SessionData = context.userdata

    cs = _require_combat(session)
    if cs.beat != combat_phase.PhaseBeat.DECLARATION:
        raise ToolError(f"Not at the declaration beat (current beat: {cs.beat}). Call resolve_phase first.")

    # The pure engine records the declarations and advances DECLARATION -> RESOLUTION.
    # An empty declarations payload is a ValueError from the engine — surface it as a
    # ToolError so the DM re-prompts rather than crashing combat.
    try:
        combat_spatial_declarations.preflight_state(cs)
        next_state, _adv = combat_phase.advance_combat_phase(cs, declarations=declarations)
        await combat_item_rider.preflight(session, next_state)
    except ValueError as e:
        raise ToolError(str(e)) from e

    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())
    session.combat_state = next_state

    response = {
        "spatial": combat_spatial.response_facts(next_state, session.acting_player_id, session.primary_player_id),
        "beat": next_state.beat,
        "round": next_state.round_number,
        "choir": choir_encounter.facts(next_state),
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
) -> str:
    """Spend one of a Boss's legendary actions to give it an extra beat this round. Call this when
    resolve_phase's ``legendary_available`` lists a Boss and you want it to act again outside its
    initiative turn — then narrate that extra action and resolve it through the normal declare/resolve
    or cast tools. A Boss has ONE legendary action per round (refreshed at the next wrap); calling
    this when the budget is spent, or on a non-Boss, is rejected. Pass the Boss's participant id."""
    return await _consume_legendary_action_impl(context, boss_id)


async def _consume_legendary_action_impl(
    context: RunContext[SessionData],
    boss_id: str,
    *,
    mutations=db_mutations,
) -> str:
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _consume_legendary_action_locked(context, boss_id, mutations=mutations)


async def _consume_legendary_action_locked(
    context: RunContext[SessionData],
    boss_id: str,
    *,
    mutations=db_mutations,
) -> str:
    session: SessionData = context.userdata
    cs = _require_combat(session)
    # The pure engine owns the 1/round rule + fail-loud (unknown / not-a-Boss / exhausted); surface
    # those as a ToolError so the DM re-prompts instead of crashing the turn.
    try:
        next_state = combat_phase.consume_legendary_action(cs, boss_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    session.combat_state = next_state
    await mutations.save_combat_state(next_state.combat_id, next_state.to_dict())
    boss = next_state.get_participant(boss_id)
    remaining = boss.legendary_actions if boss is not None else 0
    logger.info("consume_legendary_action: %s spent a legendary action (%d remaining)", boss_id, remaining)
    return json.dumps({"actor_id": boss_id, "legendary_actions_remaining": remaining})
