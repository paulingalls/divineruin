"""Draethar once-per-encounter resonance reduction with self-inflicted fire damage."""

import json
import logging
from copy import deepcopy

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import combat_resolution
import concentration_break
import condition_sources
import db
import db_mutations
import db_mutations_resonance
import db_queries
import dice
import event_types as E
import racial_resonance
import resonance_events
from combat_events import scratch_guard
from combat_support import _handle_hp_zero, _publish_sounds
from combat_ui_update import build_combat_ui_update
from game_events import publish_game_event
from kaelen_gift import trigger_iron_resolve
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

_DRAETHAR = "draethar"


async def _inner_fire_impl(context: RunContext[SessionData], **di) -> str:
    context.disallow_interruptions()
    session: SessionData = context.userdata
    async with session.combat_state_lock:
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
    player_id = session.acting_player_id
    member = session.member_state(player_id)
    logger.info("inner_fire called: player=%s", player_id)

    if session.combat_state is None:
        raise ToolError("Inner Fire can only be used in combat.")
    if member.draethar_inner_fire_used:
        raise ToolError("Inner Fire is already spent this encounter.")

    state = deepcopy(session.combat_state)
    async with scratch_guard(session), db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")
        if player.get("race") != _DRAETHAR:
            raise ToolError("Only a Draethar can use Inner Fire.")
        participant = state.get_participant(player_id)
        if participant is None:
            raise ToolError("Inner Fire requires the caster to be in the encounter.")

        reduction = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_resonance_reduction")
        damage_dice = racial_mod.get_racial_resonance_modifier(_DRAETHAR, "inner_fire_self_damage")
        fire_damage = dice_mod.roll(damage_dice).total

        new_resonance = max(0, member.resonance.current - reduction)
        was_fallen = participant.is_fallen
        overkill = max(0, fire_damage - participant.hp_current)
        hp_before = participant.hp_current
        new_hp = max(0, hp_before - fire_damage)
        session.validate_acting_player(player_id)
        await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)
        session.validate_acting_player(player_id)
        participant.hp_current = new_hp
        gift_triggered = trigger_iron_resolve(session, participant, hp_before)

        sounds: list[str] = []
        rose_hollowed = False
        if new_hp <= 0:
            _, rose_hollowed, _ = _handle_hp_zero(
                session,
                state,
                participant,
                overkill=overkill,
                was_fallen=was_fallen,
                hp_status=combat_resolution.hp_threshold_status(new_hp, participant.hp_max),
                sounds=sounds,
            )

        # A Hollowed rise flipped `type` off "player" above, and that flip is the gate: the echo's
        # HP is the monster's, not the player's, so neither players.data nor the caster's
        # concentration follows it down. Same suppression the attack path gets, same reason.
        if participant.type == "player":
            await hp_mutations_mod.update_player_hp(player_id, new_hp, conn=conn)

        participant.conditions = condition_sources.clear_charm_from_damage(
            participant.conditions, player_id, fire_damage
        )
        concentration_broken = None
        if participant.type == "player":
            concentration_broken = await concentration_break_mod.break_concentration_on_damage(
                session,
                fire_damage,
                incapacitated=new_hp <= 0,
                damaged_player_id=player_id,
                combat_state=state,
                conn=conn,
            )
        await hp_mutations_mod.save_combat_state(state.combat_id, state.to_dict(), conn=conn)

    session.combat_state = state
    resonance_reduced = member.resonance.current - new_resonance
    member.resonance.current = new_resonance
    member.draethar_inner_fire_used = True
    await resonance_events_mod.publish_resonance_changed(session, resonance_track=member.resonance, caster_id=player_id)
    await _publish_sounds(session, sounds)

    if gift_triggered:
        await publish_game_event(
            session.room,
            E.COMBAT_UI_UPDATE,
            build_combat_ui_update(session.combat_state),
            event_bus=session.event_bus,
        )

    return json.dumps(
        {
            **({"gift_triggered": gift_triggered} if gift_triggered else {}),
            "resonance_reduced": resonance_reduced,
            "fire_damage": fire_damage,
            # The participant's HP, not the burn's arithmetic: a Hollowed rise restores the echo
            # to half its max, and that is what stands on the board.
            "hp_remaining": participant.hp_current,
            "rose_hollowed": rose_hollowed,
            "state": member.resonance.state,
            "concentration_broken": concentration_broken,
        }
    )
