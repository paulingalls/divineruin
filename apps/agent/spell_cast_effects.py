"""Cast packets, conditions, and deferred client events."""

from livekit.agents.llm import ToolError

import cast_modifiers
import event_types as E
import patron_echo_choice
import spell_item_resolution
import unbound_tools
from game_events import publish_game_event
from party_state import PartyMember
from session_data import SessionData
from spell_cast_result import CastResult


async def _finish_cast(
    *,
    session: SessionData,
    spell_id: str,
    spell,
    player: dict,
    caster: PartyMember,
    target_id: str | None,
    target_ids: list[str] | None,
    conn,
    generated,
    effective_resonance,
    new_resonance,
    concentration_spell_id: object,
    ward_active,
    patron,
    race,
    wrongdoing,
    patron_resonance,
    concealment_packet,
    purified,
    locked_rows,
    revalidate_actor: bool,
    suppress_resonance_changed: bool,
    resonance,
    resonance_events_mod,
    veil_ward,
    dice_mod,
    hollow_echo,
    racial_mod,
    vaelti_warning_mod,
    echo_events_mod,
    leveling_mod,
    condition_produce_mod,
    queries_mod,
    conditions_mod,
    conditions_mutations_mod,
) -> CastResult:
    """Build the cast result, condition writes, and callbacks for post-commit publication."""
    player_id = caster.player_id
    state = resonance.get_resonance_state(effective_resonance, flickering_bonus=caster.resonance.flickering_bonus)

    # Every client event is deferred for the caller to flush post-commit (rollback-safe). The cast's own
    # RESONANCE_CHANGED is omitted when suppressed (in combat the WRAP push is authoritative) and when
    # nothing generated (a cantrip leaves the state unchanged).
    events: list = []
    events.append(
        lambda: publish_game_event(
            session.room, E.PLAY_SOUND, {"sound_name": spell.sound_id}, event_bus=session.event_bus
        )
    )
    if generated > 0 and not suppress_resonance_changed:
        events.append(
            lambda: resonance_events_mod.publish_resonance_changed(
                session, resonance_track=caster.resonance, caster_id=caster.player_id
            )
        )

    modifiers = cast_modifiers.ward_combat_modifiers(
        state, ward_active, resonance=resonance, veil_ward=veil_ward, patron=patron, source=spell.source
    )
    packet = {
        "narration_cue": spell.narration_cue,
        "audio_cue": spell.audio_cue,
        "effect": spell.mechanics,
        "state": state,
        "resonance_generated": generated,
        "resonance_modifiers": modifiers,
        "ward_active": ward_active,
    }
    if wrongdoing is not None:
        packet["wrongdoing"] = wrongdoing
    if concealment_packet is not None:
        packet["concealment"] = concealment_packet
    if patron_resonance is not None:
        packet["patron_resonance"] = patron_resonance
    spell_item_resolution.defer_inventory(session, purified, packet, events)
    if target_id is not None:
        packet["target_id"] = target_id
    # The background process voices the Vaelti warning before the echo, so its
    # deferred event must precede the echo publish.
    mastery_spent = False
    if state == "overreach":
        choice_count = next(
            (m["value"] for m in cast_modifiers.patron_modifiers(patron) if m["kind"] == "echo_roll_choice"), 1
        )
        candidates, vaelti_warned = cast_modifiers.resolve_overreach_echo(
            effective_resonance,
            race,
            ward_active,
            dice_mod=dice_mod,
            hollow_echo=hollow_echo,
            veil_ward=veil_ward,
            racial_mod=racial_mod,
            choice_count=choice_count,
        )
        if vaelti_warned:
            events.append(lambda: vaelti_warning_mod.publish_vaelti_echo_warning(session))
        if choice_count == 2:
            if revalidate_actor:
                session.validate_acting_player(player_id)
            packet["pending_choice"] = await patron_echo_choice.create(player_id, candidates, conn=conn)
        else:
            echo, mastery_spent = unbound_tools.veil_mastery(candidates[0], patron, caster)
            packet["hollow_echo"] = {
                "band": echo.band,
                "name": echo.name,
                "effect": echo.effect,
                **({"veil_mastery": True} if mastery_spent else {}),
            }
            events.append(lambda: echo_events_mod.publish_hollow_echo(session, echo))
    if spell.spell_tier == "cantrip":
        packet["damage_dice"] = leveling_mod.cantrip_damage_dice(player.get("level", 1))

    # Combat applies conditions on its working participant state; OOC must write
    # them here, within the caller's transaction after resource and echo handling.
    if spell.applies_condition is not None:
        if session.in_combat:
            packet["condition_applied"] = spell.applies_condition
        else:
            try:
                voiced = await condition_produce_mod.produce_ooc_condition(
                    spell.applies_condition,
                    spell_id,
                    target_id=target_id,
                    target_ids=target_ids,
                    caster_row=player,
                    caster_id=player_id,
                    party_member_ids=session.party.member_ids,
                    companion_id=(session.companion.id if session.companion and session.companion.is_present else None),
                    conn=conn,
                    queries_mod=queries_mod,
                    conditions_mod=conditions_mod,
                    conditions_mutations_mod=conditions_mutations_mod,
                    locked_rows=locked_rows,
                )
            except ValueError as e:
                raise ToolError(str(e)) from e
            if voiced:
                packet["condition_applied"] = spell.applies_condition
                if target_ids is not None:
                    packet["condition_targets"] = voiced

    return CastResult(
        packet=packet,
        new_resonance=new_resonance,
        concentration_spell_id=concentration_spell_id,
        generated=generated,
        events=events,
        unbound_veil_mastery_spent=mastery_spent,
    )
