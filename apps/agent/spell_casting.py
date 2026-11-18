"""Spell casting persistence and deferred client events."""

import json
import logging
from typing import cast

from livekit.agents.voice import RunContext

import ability_persistence
import character_spells
import condition_produce
import conditions
import db
import db_content_queries
import db_mutations_concentration
import db_mutations_conditions
import db_mutations_resonance
import db_queries
import dice
import hollow_echo as hollow_echo_mod
import hollow_echo_events
import leveling
import racial_resonance
import resonance as resonance_mod
import resonance_events
import spells
import vaelti_echo_warning
import veil_ward as veil_ward_mod
import ward_resolution
from session_data import SessionData
from spell_cast_resolution import _resolve_cast as _resolve_cast
from spell_cast_result import _UNCHANGED as _UNCHANGED
from spell_cast_result import CastResult as CastResult
from spell_cast_validation import _gate_spell as _gate_spell
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


async def _cast_spell_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
    db_mod=db,
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
) -> str:
    """Out-of-combat cast entry. Opens its own transaction, delegates the cast to the shared
    ``_resolve_cast`` core, then syncs the in-memory SSOT and flushes the deferred events
    post-commit. In-combat casting flows through declare_phase/resolve_phase instead (story-007)."""
    context.disallow_interruptions()
    _validate_id(spell_id, "spell_id")
    session: SessionData = context.userdata
    player_id = session.acting_player_id
    caster = session.member_state(player_id)
    logger.info("cast_spell called: spell=%s player=%s", spell_id, player_id)

    async with session.combat_state_lock:
        async with db_mod.transaction() as conn:
            result = await _resolve_cast(
                session,
                spell_id,
                conn=conn,
                caster=caster,
                revalidate_actor=True,
                target_id=target_id,
                target_ids=target_ids,
                queries_mod=queries_mod,
                content_mod=content_mod,
                persistence_mod=persistence_mod,
                resonance_mutations_mod=resonance_mutations_mod,
                resonance_events_mod=resonance_events_mod,
                spells_mod=spells_mod,
                resonance=resonance,
                leveling_mod=leveling_mod,
                veil_ward=veil_ward,
                ward_resolution_mod=ward_resolution_mod,
                hollow_echo=hollow_echo,
                dice_mod=dice_mod,
                echo_events_mod=echo_events_mod,
                racial_mod=racial_mod,
                vaelti_warning_mod=vaelti_warning_mod,
                concentration_mutations_mod=concentration_mutations_mod,
                conditions_mod=conditions_mod,
                conditions_mutations_mod=conditions_mutations_mod,
                condition_produce_mod=condition_produce_mod,
                character_spells_mod=character_spells_mod,
            )

        # Transaction committed cleanly — sync the in-memory SSOT to the persisted values, then release
        # the deferred client events. A rolled-back tx skips this (the `async with` re-raises), so the
        # session stays pristine and no event fires.
        if result.new_resonance is not None:
            caster.resonance.current = result.new_resonance
        if result.concentration_spell_id is not _UNCHANGED:
            caster.concentration.spell_id = cast("str | None", result.concentration_spell_id)
        if result.unbound_veil_mastery_spent:
            caster.unbound_veil_mastery_used = True
    await result.flush_events()
    return json.dumps(result.packet)
