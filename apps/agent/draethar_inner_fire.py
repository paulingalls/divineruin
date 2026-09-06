"""Draethar Inner Fire active racial tool for the DM agent (story-005, M3.4).

_inner_fire_impl is the Draethar's once-per-encounter pressure valve (spec magic.md:262-268): the
caster's skin flares and the inner fire purges Veil disturbance — reduce current Resonance by 3,
but take 1d6 unpreventable self fire damage. The -3 / "1d6" values are read from the racial
table (racial_resonance, story-001), not hardcoded. Unlike the passive racials this is an active
combat action, gated to once per encounter via session.draethar_inner_fire_used (reset at
encounter boundaries, beside the per-member weapon flags). It enters via activate_tools.activate —
the reserved 'draethar_inner_fire' token (M25 Phase-5 story-002 folded the standalone inner_fire
@function_tool wrapper into it).

It is combat-scoped (the "encounter" is a combat): a player's HP lives in two places during
combat — the in-memory CombatParticipant.hp_current and persisted players.data — so this writes
BOTH, exactly as combat_turn.py does (participant then update_player_hp). Every user-facing
failure is a ToolError raised BEFORE any write, so an ineligible use changes nothing.

Mirrors the veil_ward_tools seam: module-injection keyword args (db_mod/queries_mod/
hp_mutations_mod/resonance_mutations_mod/resonance_events_mod/racial_mod/dice_mod) for test
mocking, a single db.transaction() block (the participant's HP and its zero-HP transition are
written inside it), and a post-commit in-memory sync + RESONANCE_CHANGED push (mirroring the
spell cast path). The whole call runs under session.combat_end_lock: it mutates the live
CombatState, and the paths that adopt a copy of it would otherwise erase the burn.
"""

import json
import logging

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import combat_resolution
import concentration_break
import db
import db_mutations
import db_mutations_resonance
import db_queries
import dice
import racial_resonance
import resonance_events
from combat_support import _handle_hp_zero, _publish_sounds
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

_DRAETHAR = "draethar"


async def _inner_fire_impl(context: RunContext[SessionData], **di) -> str:
    """Serialise the burn against the paths that ADOPT a copy of the combat state.

    resolve_phase and request_death_save both snapshot ``combat_state``, await a transaction, then
    rebind the session to the snapshot. This tool writes the LIVE participant in place, so an
    unlocked burn landing in that gap is erased wholesale on adoption — and since story-026 routed
    it through ``_handle_hp_zero`` that is no longer one HP field but the fall itself
    (``is_fallen``/``is_dead``/``type``/``conditions``), while the once-per-encounter spend stays
    gone. Holding the lock for the WHOLE call also means the gates below re-read a combat_state a
    concurrent end_combat has already cleared, and refuse honestly rather than burning a fight
    that is over.

    Not reentrant, and safe: ``activate`` dispatches here directly (activate_tools), so no lock
    holder reaches this tool.
    """
    context.disallow_interruptions()
    session: SessionData = context.userdata
    async with session.combat_end_lock:
        return await _inner_fire_locked(context, **di)


async def _inner_fire_locked(
    context: RunContext[SessionData],
    *,
    db_mod=db,
    queries_mod=db_queries,
    hp_mutations_mod=db_mutations,
    resonance_mutations_mod=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    racial_mod=racial_resonance,
    dice_mod=dice,
    concentration_break_mod=concentration_break,
) -> str:
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("inner_fire called: player=%s", player_id)

    # Gates FIRST, all before any write (ineligible use changes nothing). Combat gate first so the
    # player fetch is skipped when there's no encounter.
    if session.combat_state is None:
        raise ToolError("Inner Fire can only be used in combat.")
    if session.draethar_inner_fire_used:
        raise ToolError("Inner Fire is already spent this encounter.")

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")
        if player.get("race") != _DRAETHAR:
            raise ToolError("Only a Draethar can use Inner Fire.")
        participant = session.combat_state.get_participant(player_id)
        if participant is None:
            raise ToolError("Inner Fire requires the caster to be in the encounter.")

        reduction = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_resonance_reduction")
        damage_dice = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_self_damage")
        fire_damage = dice_mod.roll(damage_dice).total

        new_resonance = max(0, session.resonance.current - reduction)
        was_fallen = participant.is_fallen
        overkill = max(0, fire_damage - participant.hp_current)
        new_hp = max(0, participant.hp_current - fire_damage)
        participant.hp_current = new_hp

        # The zero-HP transition has ONE owner. Self-damage knocks on the same door as a blow;
        # bypassing it is what left a burned-out Draethar at 0 HP with is_fallen False, invisible
        # to death_saves_due and to request_death_save (bug 16c5f8a0). In-tx, on the live
        # participant, with the rollback window that opens: note c4607772.
        sounds: list[str] = []
        rose_hollowed = False
        if new_hp <= 0:
            _, rose_hollowed = _handle_hp_zero(
                session,
                participant,
                overkill=overkill,
                was_fallen=was_fallen,
                hp_status=combat_resolution.hp_threshold_status(new_hp, participant.hp_max),
                sounds=sounds,
            )

        await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)
        # A Hollowed rise flipped `type` off "player" above, and that flip is the gate: the echo's
        # HP is the monster's, not the player's, so neither players.data nor the caster's
        # concentration follows it down. Same suppression the attack path gets, same reason.
        if participant.type == "player":
            await hp_mutations_mod.update_player_hp(player_id, new_hp, conn=conn)

    # Transaction committed — sync the in-memory SSOTs and push the HUD state.
    resonance_reduced = session.resonance.current - new_resonance
    session.resonance.current = new_resonance
    session.draethar_inner_fire_used = True
    # Persist the combat state so the participant's self-damage survives a mid-encounter crash,
    # mirroring combat_turn (participant HP lives in combat_instances, not just players.data).
    await hp_mutations_mod.save_combat_state(session.combat_state.combat_id, session.combat_state.to_dict())
    await resonance_events_mod.publish_resonance_changed(session)
    await _publish_sounds(session, sounds)

    # The self-inflicted fire damage is still damage: a concentrating Draethar rolls the CON save
    # like any other combat damage (incapacitated when the burn drops them to 0 HP).
    concentration_broken = None
    if participant.type == "player":
        concentration_broken = await concentration_break_mod.break_concentration_on_damage(
            session, fire_damage, incapacitated=new_hp <= 0, damaged_player_id=player_id
        )
    if concentration_broken is not None:
        # A broken concentration spell that granted a beneficial condition strips it from the
        # in-combat participants (M4.8 story-006). That mutation lands AFTER the save_combat_state
        # above, so re-persist — otherwise the dropped +1d4 reappears on the next combat_state
        # reload. Only fires when concentration actually broke (rare); a no-condition spell makes
        # this an idempotent re-write of the already-saved state.
        await hp_mutations_mod.save_combat_state(session.combat_state.combat_id, session.combat_state.to_dict())

    return json.dumps(
        {
            "resonance_reduced": resonance_reduced,
            "fire_damage": fire_damage,
            # The participant's HP, not the burn's arithmetic: a Hollowed rise restores the echo
            # to half its max, and that is what stands on the board.
            "hp_remaining": participant.hp_current,
            "rose_hollowed": rose_hollowed,
            # Canonical band: ResonanceTrack.state derives from session.resonance.current (set
            # above to new_resonance) + flickering_bonus. For a Draethar the bonus is always 0,
            # so this equals the old get_resonance_state(new_resonance) — one SSOT for the band.
            "state": session.resonance.state,
            "concentration_broken": concentration_broken,
        }
    )
