"""Death-save combat tool — request_death_save.

Extracted from combat_turn.py (story-004, debt faa6dd19ab64) to bring that file
back under the 500-line cap. Behavior unchanged; this is the player's 0-HP death
saving throw (nat-20 revives, three successes stabilize, three failures kill).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import creation_deities
import db
import db_mutations
import event_types as E
from combat_support import _publish_sounds, _require_combat
from db_errors import db_tool
from game_events import publish_game_event
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
    """Roll a death saving throw for a fallen party member. Call this when someone is at 0 HP and
    it's their turn (or when prompted). Nat 20 restores 1 HP. Three successes stabilize, three
    failures mean death. Omit player_id when only one ally is down; when several are, name the one
    who rolls — each carries their own successes, failures, and patron bonus."""
    return await _request_death_save_impl(context, player_id)


def _resolve_faller(cs, player_id: str | None):
    """The participant whose save this is. Enemies never roll — they simply lie there.

    Naming is required once more than one ally is down. The old code looked up session.player_id
    unconditionally: a fallen NON-primary could never roll (the standing primary failed the
    is_fallen gate), and when both were down the primary was rolled twice, its counters and HP
    corrupted while the member actually dying was ignored."""
    candidates = [p for p in cs.participants if p.type != "enemy" and p.is_fallen and not p.is_dead]

    if player_id is not None:
        chosen = cs.get_participant(player_id)
        if chosen is None:
            raise ToolError(f"No one named {player_id} is in this fight.")
        if chosen.type == "enemy":
            raise ToolError(f"{chosen.name} is an enemy — enemies do not roll death saves.")
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
) -> str:
    """Serialise the death save on the session's combat-end lock, like resolve_phase and the
    reaction spend.

    This call snapshots the whole CombatState, awaits a transaction, then REBINDS
    session.combat_state to the snapshot. Unlocked, any field another path committed on the live
    state during that await is silently erased on adoption — a reaction spent through
    ability_tools (which does hold this lock) has its resource deduction committed and its
    reactions_available flag restored to True, so the player pays and keeps the reaction.
    Not reentrant, and safe: no lock holder reaches this tool (only combat_agent's toolset does)."""
    session: SessionData = context.userdata
    async with session.combat_end_lock:
        return await _request_death_save_locked(context, player_id, mutations=mutations, db_mod=db_mod)


async def _request_death_save_locked(
    context: RunContext[SessionData],
    player_id: str | None = None,
    *,
    mutations=db_mutations,
    db_mod=db,
) -> str:
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs = _require_combat(session)

    # Resolve against the LIVE state (read-only), then roll and apply to a copy: the live
    # CombatState is adopted only post-commit, so a failed persist strands no advanced counter
    # in memory for the next reload to silently lose. Mirrors resolve_phase's contract.
    faller = _resolve_faller(cs, player_id)

    # Mortaen patrons roll death saves at +2 (M4.4 story-004). Read the ROLLER's own patron, not the
    # primary's — patron_id lives on PartyMember. A companion has no member row and no patron.
    member = session.party.member(faller.id)
    bonus = creation_deities.patron_death_save_bonus(member.patron_id if member is not None else "none")
    result = combat_resolution.resolve_death_save(
        faller.death_save_successes,
        faller.death_save_failures,
        bonus=bonus,
    )

    state = CombatState.from_dict(cs.to_dict())  # working copy; adopted post-commit
    working = state.get_participant(faller.id)
    assert working is not None  # copied from the state we just resolved against
    working.death_save_successes = result.total_successes
    working.death_save_failures = result.total_failures

    sounds: list[str] = []
    revive_player_id: str | None = None

    if result.critical_success:
        # Nat 20: regain 1 HP, no longer fallen
        working.hp_current = 1
        working.is_fallen = False
        working.death_save_successes = 0
        working.death_save_failures = 0
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
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)

    # Committed — now adopt the rolled state and release its events.
    session.combat_state = state

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
    logger.info("request_death_save result: d%d, %s", result.roll, outcome)
    return json.dumps(response)
