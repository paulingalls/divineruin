"""Draethar once-per-encounter resonance reduction with self-inflicted fire damage."""

import json
import logging
from copy import deepcopy

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import combat_resolution
import concentration_break
import condition_sources
import conditions
import db
import db_mutations
import db_mutations_resonance
import db_queries
import dice
import encounter_facts
import event_types as E
import racial_resonance
import resonance
import resonance_events
import zhael_fate
from combat_damage import _handle_hp_zero
from combat_events import isolated_publish, scratch_guard
from combat_fate_rolls import PacketRolls, PhaseRolls
from combat_sound_events import publish_combat_sounds as _publish_sounds
from combat_ui_update import build_combat_ui_update
from game_events import publish_game_event
from patron_ability_events import publish_patron_abilities
from patron_zero_hp import lock_damage_players, trigger_damage_gifts
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
    if member.draethar_inner_fire_used or player_id in session.combat_state.inner_fire_used_by:
        raise ToolError("Inner Fire is already spent this encounter.")

    if session.combat_state.inner_fire_continuation is not None:
        raise ToolError("Call resolve_phase to finish the held Inner Fire roll.")
    state = deepcopy(session.combat_state)
    fate_rolls = PhaseRolls()
    async with scratch_guard(session), db_mod.transaction() as conn:
        players = await lock_damage_players(session, player_id, queries=queries_mod, conn=conn)
        player = players.get(player_id)
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
        counted_before = encounter_facts.counted_death(participant)
        was_fallen = participant.is_fallen
        hp_before = participant.hp_current
        new_hp = max(conditions.damage_hp_floor(participant.conditions), hp_before - fire_damage)
        overkill = max(0, fire_damage - hp_before) if new_hp == 0 else 0
        session.validate_acting_player(player_id)
        await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)
        session.validate_acting_player(player_id)
        participant.hp_current = new_hp
        gift = await trigger_damage_gifts(
            session, state, participant, hp_before, players=players, queries=queries_mod, conn=conn
        )
        final_hp = participant.hp_current

        sounds: list[str] = []
        rose_hollowed = False
        if final_hp <= 0:
            _, rose_hollowed, _ = _handle_hp_zero(
                session,
                state,
                participant,
                overkill=overkill,
                was_fallen=was_fallen,
                hp_status=combat_resolution.hp_threshold_status(final_hp, participant.hp_max),
                sounds=sounds,
            )

        # A Hollowed rise flipped `type` off "player" above, and that flip is the gate: the echo's
        # HP is the monster's, not the player's, so neither players.data nor the caster's
        # concentration follows it down. Same suppression the attack path gets, same reason.
        if participant.type == "player":
            await hp_mutations_mod.update_player_hp(player_id, final_hp, conn=conn)

        participant.conditions = condition_sources.clear_charm_from_damage(
            participant.conditions, player_id, fire_damage
        )
        facts = {
            **gift,
            "resonance_reduced": member.resonance.current - new_resonance,
            "fire_damage": fire_damage,
            "hp_remaining": participant.hp_current,
            "rose_hollowed": rose_hollowed,
            "state": resonance.get_resonance_state(new_resonance, flickering_bonus=member.resonance.flickering_bonus),
            "concentration_broken": None,
        }
        renewals = await encounter_facts.renew_on_death(
            state, participant, counted_before, queries=queries_mod, conn=conn
        )
        if renewals:
            facts["focus_renewals"] = renewals
        steps: dict = {}
        if participant.type == "player":
            kwargs = (
                {"progress": PacketRolls(fate_rolls, steps, queries_mod, conn)} if session.fate_lock.locked() else {}
            )
            facts["concentration_broken"] = await concentration_break_mod.break_concentration_on_damage(
                session,
                fire_damage,
                incapacitated=final_hp <= 0,
                damaged_player_id=player_id,
                combat_state=state,
                conn=conn,
                **kwargs,
            )
        state.inner_fire_used_by.append(player_id)
        if fate_rolls.pending is not None:
            state.inner_fire_continuation = {"player_id": player_id, "facts": facts, "steps": steps}
        await hp_mutations_mod.save_combat_state(state.combat_id, state.to_dict(), conn=conn)

    session.combat_state = state
    member.resonance.current = new_resonance
    member.draethar_inner_fire_used = True
    if fate_rolls.pending is not None:

        async def resume(selected):
            async with session.combat_state_lock:
                return zhael_fate.Resumed(
                    await resume_inner_fire(
                        session,
                        db_mod=db_mod,
                        queries=queries_mod,
                        mutations=hp_mutations_mod,
                        concentration_break_mod=concentration_break_mod,
                        kept=selected,
                    )
                )

        session.fate_offer = fate_rolls.pending.offer(resume)
        facts = {**facts, **session.fate_offer.response()}

    with isolated_publish("Inner Fire resonance push"):
        await resonance_events_mod.publish_resonance_changed(
            session, resonance_track=member.resonance, caster_id=player_id
        )
    with isolated_publish("Inner Fire sounds"):
        await _publish_sounds(session, sounds)
    if gift_owner := gift.get("gift_owner"):
        with isolated_publish("Inner Fire patron abilities"):
            await publish_patron_abilities(session.room, gift_owner["id"], session.event_bus)
    if gift:
        with isolated_publish("Inner Fire combat UI"):
            await publish_game_event(
                session.room, E.COMBAT_UI_UPDATE, build_combat_ui_update(state), event_bus=session.event_bus
            )
    return json.dumps(facts)


async def resume_inner_fire(session, *, db_mod, queries, mutations, concentration_break_mod, kept=None) -> dict:
    state = deepcopy(session.combat_state)
    assert state is not None and state.inner_fire_continuation is not None
    cursor = state.inner_fire_continuation
    player_id = cursor["player_id"]
    facts = cursor["facts"]
    fate_rolls = PhaseRolls(kept=kept)
    async with scratch_guard(session), db_mod.transaction() as conn:
        facts["concentration_broken"] = await concentration_break_mod.break_concentration_on_damage(
            session,
            facts["fire_damage"],
            incapacitated=False,
            damaged_player_id=player_id,
            combat_state=state,
            conn=conn,
            progress=PacketRolls(fate_rolls, cursor["steps"], queries, conn),
        )
        assert fate_rolls.pending is None and fate_rolls.kept is None
        state.inner_fire_continuation = None
        await mutations.save_combat_state(state.combat_id, state.to_dict(), conn=conn)
    session.combat_state = state
    session.member_state(player_id).draethar_inner_fire_used = True
    zhael_fate.effects_committed(session)
    return facts
