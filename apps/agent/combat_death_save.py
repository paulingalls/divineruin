"""Death saves for fallen players and companions."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import creation_deities
import db
import db_mutations
import db_queries
import encounter_facts
import event_types as E
import zhael_fate
from combat_down import revive, sync_companion_consciousness
from combat_participant import CombatParticipant
from combat_sound_events import publish_combat_sounds as _publish_sounds
from combat_support import _require_combat
from db_errors import db_tool
from game_events import publish_game_event
from patron_synergy_combat import MORTAEN_HOLD_THE_CROSSING, marshal_death_save_bonus
from session_data import CombatState, SessionData
from tool_support import (
    SOUND_DEATH_SAVE_CRITICAL,
    SOUND_DEATH_SAVE_FAIL,
    SOUND_DEATH_SAVE_SUCCESS,
    SOUND_PLAYER_DEATH,
    SOUND_PLAYER_STABILIZED,
)

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def request_death_save(
    context: RunContext[SessionData],
    player_id: str | None = None,
) -> str:
    """Roll a death saving throw for a fallen player or companion at 0 HP when prompted.
    Hollowed echoes never roll. Nat 20 restores 1 HP. Three successes stabilize, three failures
    mean death. Omit player_id when only one ally is down. When several are down, name who rolls.
    Each ally carries their own successes, failures, and patron bonus."""
    return await _request_death_save_impl(context, player_id)


def _resolve_faller(cs: CombatState, player_id: str | None) -> CombatParticipant:
    candidates = [p for p in cs.participants if p.is_ally and p.is_fallen and not p.is_dead]

    if player_id is not None:
        chosen = cs.get_participant(player_id)
        if chosen is None:
            raise ToolError(f"No one named {player_id} is in this fight.")
        if chosen.type == "enemy":
            raise ToolError(f"{chosen.name} is an enemy — enemies do not roll death saves.")
        if chosen.type == "temporary_hollowed":
            raise ToolError(f"{chosen.name} is a Hollowed echo. Hollowed echoes do not roll death saves.")
        if not chosen.is_fallen or chosen.is_dead:
            raise ToolError(f"{chosen.name} has not fallen. Death saves only apply at 0 HP.")
        return chosen

    if not candidates:
        raise ToolError("No one has fallen. Death saves only apply at 0 HP.")
    if len(candidates) > 1:
        names = ", ".join(p.id for p in candidates)
        raise ToolError(f"More than one ally is down — name who rolls: {names}")
    return candidates[0]


async def _request_death_save_impl(
    context: RunContext[SessionData],
    player_id: str | None = None,
    *,
    mutations=db_mutations,
    db_mod=db,
    queries=db_queries,
) -> str:
    """Serialise the death save on the session's combat-state lock, like resolve_phase and the
    reaction spend.

    This call snapshots the whole CombatState, awaits a transaction, then REBINDS
    session.combat_state to the snapshot. Unlocked, any field another path committed on the live
    state during that await is silently erased on adoption — a reaction spent through
    ability_tools (which does hold this lock) has its resource deduction committed and its
    reactions_available spend record reverted to unspent, so the player pays and keeps the
    reaction, and story-018 loses the binding that says which blow it answered.
    Not reentrant, and safe: no lock holder reaches this tool (only combat_agent's toolset does)."""
    session: SessionData = context.userdata
    async with session.combat_state_lock:
        return await _roll_death_save(context, player_id, mutations=mutations, db_mod=db_mod, queries=queries)


async def _roll_death_save(
    context: RunContext[SessionData],
    player_id: str | None = None,
    *,
    mutations=db_mutations,
    db_mod=db,
    queries=db_queries,
) -> str:
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs = _require_combat(session)

    # Resolve against the LIVE state (read-only), then roll and apply to a copy: the live
    # CombatState is adopted only post-commit, so a failed persist strands no advanced counter
    # in memory for the next reload to silently lose. Mirrors resolve_phase's contract.
    faller = _resolve_faller(cs, player_id)

    member = session.party.member(faller.id)
    personal_bonus = creation_deities.patron_death_save_bonus(member.patron_id if member is not None else "none")
    synergy_bonus = await marshal_death_save_bonus(cs, queries=queries)
    bonus = personal_bonus + synergy_bonus
    bonus_receipt = {
        "bonus": bonus,
        "synergy_bonus": synergy_bonus,
        "synergy_clause_id": MORTAEN_HOLD_THE_CROSSING if synergy_bonus else None,
    }
    successes, failures = faller.death_save_successes, faller.death_save_failures
    faller_id = faller.id

    def roll(face=None):
        return combat_resolution.resolve_death_save(successes, failures, bonus=bonus, face=face)

    result = roll()
    candidates = await zhael_fate.candidates(session)
    if candidates.choices(faller_id):

        async def resume(kept):
            async with session.combat_state_lock:
                current = session.combat_state
                if current is None:
                    return zhael_fate.cancel(session, "Combat ended while the death save was held.")
                participant = current.get_participant(faller_id)
                if (
                    current.combat_id != cs.combat_id
                    or participant is None
                    or not participant.is_fallen
                    or participant.is_dead
                    or (participant.death_save_successes, participant.death_save_failures) != (successes, failures)
                ):
                    return zhael_fate.cancel(session, "The fallen ally's state changed while the death save was held.")
                response = await _request_death_save_locked(
                    session,
                    current,
                    faller_id,
                    kept,
                    mutations,
                    db_mod,
                    queries=queries,
                    bonus_receipt=bonus_receipt,
                    resumed=True,
                )
                return zhael_fate.Resumed(json.loads(response))

        offer = zhael_fate.make_offer(
            "death_save",
            faller_id,
            result,
            candidates,
            numbers=lambda r: (r.roll, r.roll + bonus),
            reroll=roll,
            flip=roll,
            resume=resume,
        )
        if offer is not None:
            session.fate_offer = offer
            return json.dumps(offer.response())

    return await _request_death_save_locked(
        session, cs, faller_id, result, mutations, db_mod, queries=queries, bonus_receipt=bonus_receipt
    )


async def _request_death_save_locked(
    session,
    cs,
    faller_id,
    result,
    mutations,
    db_mod,
    *,
    queries,
    bonus_receipt: dict[str, int | str | None],
    resumed=False,
) -> str:
    state = CombatState.from_dict(cs.to_dict())  # working copy; adopted post-commit
    working = state.get_participant(faller_id)
    assert working is not None  # copied from the state we just resolved against
    counted_before = encounter_facts.counted_death(working)
    working.death_save_successes = result.total_successes
    working.death_save_failures = result.total_failures
    if result.success:
        state.encounter_facts["death_save_success_round"][faller_id] = state.round_number

    sounds: list[str] = []
    revive_player_id: str | None = None

    if result.critical_success:
        revive(working, 1)
        # Only a player has a players.data HP row. A companion's HP lives on the combat row alone;
        # writing here would have restored the PLAYER's HP for a companion's lucky roll.
        if working.type == "player":
            revive_player_id = working.id
        sounds.append(SOUND_DEATH_SAVE_CRITICAL)
    elif result.stabilized:
        sounds.append(SOUND_PLAYER_STABILIZED)
    elif result.dead:
        sounds.append(SOUND_PLAYER_DEATH)
    elif result.success:
        sounds.append(SOUND_DEATH_SAVE_SUCCESS)
    else:
        sounds.append(SOUND_DEATH_SAVE_FAIL)

    # ONE transaction spans both writes: split apart, a crash between them left players.data holding
    # a live 1-HP character that the combat_instances SSOT still called fallen, and the DM went on
    # prompting death saves for someone already revived.
    async with db_mod.transaction() as conn:
        if revive_player_id is not None:
            await mutations.update_player_hp(revive_player_id, 1, conn=conn)
        renewals = await encounter_facts.renew_on_death(state, working, counted_before, queries=queries, conn=conn)
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)

    # Committed — now adopt the rolled state and release its events.
    sync_companion_consciousness(session, state)
    session.combat_state = state
    if resumed:
        zhael_fate.effects_committed(session)

    # Publish events
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "death_save",
            "roll": result.roll,
            "success": result.success,
            "critical_success": result.critical_success,
            "critical_failure": result.critical_failure,
            "total_successes": result.total_successes,
            "total_failures": result.total_failures,
            "dramatic": result.dramatic,
            "context": result.context,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    outcome = "stabilized" if result.stabilized else "dead" if result.dead else "continuing"
    if result.critical_success:
        outcome = "revived"
    session.record_event(f"Death save: d{result.roll}, {outcome}")

    response = {
        **bonus_receipt,
        "roll": result.roll,
        "success": result.success,
        "critical_success": result.critical_success,
        "critical_failure": result.critical_failure,
        "total_successes": result.total_successes,
        "total_failures": result.total_failures,
        "stabilized": result.stabilized,
        "dead": result.dead,
        "revived": result.critical_success,
        "narrative_hint": result.narrative_hint,
        "dramatic": result.dramatic,
        "context": result.context,
    }
    if renewals:
        response["focus_renewals"] = renewals
    logger.info("request_death_save result: d%d, %s", result.roll, outcome)
    return json.dumps(response)
