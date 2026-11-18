"""Shared cast orchestration and resource persistence."""

from livekit.agents.llm import ToolError

import ability_persistence
import cast_modifiers
import character_spells
import combat_hollow_resonance
import concealment
import condition_produce
import conditions
import db_content_queries
import db_mutations_concentration
import db_mutations_conditions
import db_mutations_resonance
import db_queries
import dice
import hollow_echo as hollow_echo_mod
import hollow_echo_events
import leveling
import patron_cast_context
import racial_resonance
import resonance as resonance_mod
import resonance_events
import spell_item_resolution
import spells
import vaelti_echo_warning
import veil_ward as veil_ward_mod
import ward_resolution
from combat_terrain import resolve_terrain
from party_state import PartyMember
from session_data import CombatState, SessionData
from spell_cast_effects import _finish_cast
from spell_cast_result import _UNCHANGED, CastResult
from spell_cast_validation import _prepare_cast


async def _resolve_cast(
    session: SessionData,
    spell_id: str,
    *,
    conn,
    caster: PartyMember | None = None,
    revalidate_actor: bool = False,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    player: dict | None = None,
    combat_state: CombatState | None = None,
    suppress_resonance_changed: bool = False,
    queries_mod=db_queries,
    content_mod=db_content_queries,
    persistence_mod=ability_persistence,
    resonance_mutations_mod=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    spells_mod=spells,
    resonance=resonance_mod,
    leveling_mod=leveling,
    veil_ward=veil_ward_mod,
    ward_resolution_mod=ward_resolution,
    hollow_echo=hollow_echo_mod,
    dice_mod=dice,
    echo_events_mod=hollow_echo_events,
    racial_mod=racial_resonance,
    vaelti_warning_mod=vaelti_echo_warning,
    concentration_mutations_mod=db_mutations_concentration,
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    condition_produce_mod=condition_produce,
    character_spells_mod=character_spells,
) -> CastResult:
    """Resolve a cast within the caller's transaction.

    Callers sync the caster's resonance, concentration, and mastery mirrors and
    flush result events only after commit, so rollback leaves those untouched.
    Combat resonance instead stages on the supplied working combat state.

    Combat supplies its locked player row and suppresses the resonance push
    because WRAP owns the authoritative HUD update. OOC locks its own rows.
    """
    caster = caster or session.party.primary
    spell, player, target_ids, item_target, locked_rows = await _prepare_cast(
        session,
        caster,
        spell_id,
        conn=conn,
        player=player,
        combat_state=combat_state,
        target_id=target_id,
        target_ids=target_ids,
        content_mod=content_mod,
        spells_mod=spells_mod,
        condition_produce_mod=condition_produce_mod,
        queries_mod=queries_mod,
        character_spells_mod=character_spells_mod,
    )
    player_id = caster.player_id
    race = player.get("race")
    patron = (player.get("divine_favor") or {}).get("patron")
    current_focus = (player.get("focus") or {}).get("current", 0)

    terrain = (
        await resolve_terrain(session, combat_state=combat_state, content_mod=content_mod)
        if spell.source == "primal"
        or any(m["applies_to"] == "natural_ground" for m in cast_modifiers.patron_modifiers(patron))
        else None
    )
    # An active Veil Ward halves generated Resonance. Resolved from the DB, never the in-memory
    # mirror: expiry is lazy, so a lapsed or walked-away-from ward would otherwise halve casts forever.
    ward_active = (
        await ward_resolution_mod.resolve_scope_ward(session, conn=conn, combat_state=combat_state) is not None
    )

    def generation(cast_patron: str | None) -> int:
        try:
            raw = cast_modifiers.compute_generated_resonance(
                spell, race, terrain=terrain, resonance=resonance, racial_mod=racial_mod, patron=cast_patron
            )
        except ValueError as e:
            raise ToolError(f"Cannot cast {spell.name}: {e}") from e
        raw = combat_hollow_resonance.cast_generation(combat_state or session.combat_state, caster, spell, raw)
        return cast_modifiers.apply_ward_halving(raw, ward_active, veil_ward=veil_ward)

    generated, patron_resonance, wrongdoing = await patron_cast_context.apply_patron(
        generation(patron),
        generation(None),
        patron,
        session,
        player,
        terrain=terrain,
        conn=conn,
        queries_mod=queries_mod,
        spell=spell,
        combat_state=combat_state,
        target_id=target_id,
        target_ids=target_ids,
    )

    concealment_packet = None
    if concealment.is_concealed(player):
        if revalidate_actor:
            session.validate_acting_player(player_id)
        concealment_packet = await concealment.transition(player, False, ended_by="cast", conn=conn)

    purified = None
    if item_target is not None:
        purified = await spell_item_resolution.purify_item(
            session, item_target, conn, caster_id=player_id, revalidate_actor=revalidate_actor
        )
    if spell.focus_cost > 0:
        if revalidate_actor:
            session.validate_acting_player(player_id)
        await persistence_mod.update_player_resources(player_id, focus=current_focus - spell.focus_cost, conn=conn)

    # The post-cast total is persisted via conn but kept LOCAL: the caller syncs session.resonance
    # post-commit, so a rollback leaves the in-memory track untouched.
    effective_resonance = cast_modifiers.compute_effective_resonance(
        generated,
        combat_hollow_resonance.current_total(combat_state, caster),
        race,
        session.in_combat,
        resonance=resonance,
        racial_mod=racial_mod,
    )
    new_resonance = effective_resonance if generated > 0 else None
    if generated > 0:
        if revalidate_actor:
            session.validate_acting_player(player_id)
        await resonance_mutations_mod.update_player_resonance(player_id, effective_resonance, conn=conn)
        combat_hollow_resonance.stage_total(combat_state, player_id, effective_resonance)

    concentration_spell_id: object = _UNCHANGED
    if spell.concentration:
        if revalidate_actor:
            session.validate_acting_player(player_id)
        await concentration_mutations_mod.update_player_concentration(player_id, spell_id, conn=conn)
        concentration_spell_id = spell_id

    return await _finish_cast(
        session=session,
        spell_id=spell_id,
        spell=spell,
        player=player,
        caster=caster,
        target_id=target_id,
        target_ids=target_ids,
        conn=conn,
        generated=generated,
        effective_resonance=effective_resonance,
        new_resonance=new_resonance,
        concentration_spell_id=concentration_spell_id,
        ward_active=ward_active,
        patron=patron,
        race=race,
        wrongdoing=wrongdoing,
        patron_resonance=patron_resonance,
        concealment_packet=concealment_packet,
        purified=purified,
        locked_rows=locked_rows,
        revalidate_actor=revalidate_actor,
        suppress_resonance_changed=suppress_resonance_changed,
        resonance=resonance,
        resonance_events_mod=resonance_events_mod,
        veil_ward=veil_ward,
        dice_mod=dice_mod,
        hollow_echo=hollow_echo,
        racial_mod=racial_mod,
        vaelti_warning_mod=vaelti_warning_mod,
        echo_events_mod=echo_events_mod,
        leveling_mod=leveling_mod,
        condition_produce_mod=condition_produce_mod,
        queries_mod=queries_mod,
        conditions_mod=conditions_mod,
        conditions_mutations_mod=conditions_mutations_mod,
    )
