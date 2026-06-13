"""Spell casting tools for the DM agent (M3.3 story-004).

cast_spell is the real cast path: it validates a named spell, gates the caster's
Focus and deducts it, reads the Resonance the cast generates from the catalog's
designed per-spell resonance_by_source[source] (the SSOT, decision
resonance-by-source-ssot), accrues that onto the session's ResonanceTrack and
persists it, then returns an effect + narration_cue + audio_cue packet for the DM
to voice. The M3.1 rules engine (resonance.calculate_resonance_generated) is the
fallback only when a spell carries no entry for its source. Cantrips (focus_cost 0)
cost no Focus, generate 0 Resonance, and scale their damage via
leveling.cantrip_damage_dice(level).

get_spell_info is a read-only lookup returning the full catalog data for a spell so
the DM can describe it before casting.

Resonance stays hidden from the player (CLAUDE.md golden rule #3, spec magic.md:98):
the packet carries the qualitative `state` (stable/flickering/overreach) and the
free combat modifiers, never asks the LLM to compute them. The deterministic numbers
come from the rules engine; the LLM only decides when to cast and how to narrate.

Mirrors the ability_tools seam exactly: a thin @function_tool wrapper over an _impl
with module-injection keyword args (db_mod/queries_mod/persistence_mod/
resonance_mutations_mod/resonance_events_mod/spells_mod/resonance_mod/leveling_mod)
for test mocking, a
single db.transaction() block, and ToolError for every user-facing failure.

Terrain note: every catalog spell (primal included) carries a designed
resonance_by_source baseline, so casts no longer depend on terrain — a primal
non-cantrip casts via its catalog baseline. The fallback formula
(calculate_resonance_generated) only reaches the terrain lookup for an in-code
primal build that carries no resonance_by_source entry, and since no runtime
location->terrain map exists yet (terrain defaults to "normal"), that one path
still fails loud as a ToolError until terrain wiring lands (M3.4).
"""

import json
import logging
from dataclasses import asdict

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import db
import db_mutations_resonance
import db_queries
import leveling
import resonance as resonance_mod
import resonance_events
import spells
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# Default terrain for resonance generation. Only consulted for PRIMAL non-cantrips
# (see module docstring); a real location->terrain map is M3.4 work.
_DEFAULT_TERRAIN = "normal"


@function_tool()
async def get_spell_info(
    context: RunContext[SessionData],
    spell_id: str,
) -> str:
    """Look up the full details of a spell by its id (e.g. 'arcane_bolt').
    Call when the player or DM needs a spell's cost, source, tier, mechanics, or
    narration before casting. Read-only — does not cast or spend anything. Returns
    the spell's full catalog data as JSON; raises if the spell id is unknown."""
    return await _get_spell_info_impl(context, spell_id)


async def _get_spell_info_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    spells_mod=spells,
) -> str:
    _validate_id(spell_id, "spell_id")
    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return json.dumps(asdict(spell))


@function_tool()
@db_tool
async def cast_spell(
    context: RunContext[SessionData],
    spell_id: str,
) -> str:
    """Cast a spell by its id (e.g. 'arcane_bolt'). Call when the caster casts a
    known spell. Validates and deducts the spell's Focus cost (rejecting if the
    caster can't afford it), builds the hidden Resonance the cast generates, and
    returns the effect, narration_cue, and audio_cue to voice plus the resulting
    Resonance state and its combat modifiers. Cantrips are free and scale damage
    with level — the packet's damage_dice carries the scaled dice."""
    return await _cast_spell_impl(context, spell_id)


async def _cast_spell_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    persistence_mod=ability_persistence,
    resonance_mutations_mod=db_mutations_resonance,
    resonance_events_mod=resonance_events,
    spells_mod=spells,
    resonance=resonance_mod,
    leveling_mod=leveling,
) -> str:
    context.disallow_interruptions()
    _validate_id(spell_id, "spell_id")
    session: SessionData = context.userdata
    player_id = session.player_id
    logger.info("cast_spell called: spell=%s player=%s", spell_id, player_id)

    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as e:
        raise ToolError(str(e)) from e

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

        # Focus gate FIRST — reject before any write so an unaffordable cast deducts
        # nothing (AC1). Cantrips (focus_cost 0) skip the gate and the deduction.
        focus_pool = player.get("focus") or {}
        current_focus = focus_pool.get("current", 0)
        if spell.focus_cost > 0:
            if "current" not in focus_pool:
                raise ToolError(f"{spell.name} costs Focus but you have no Focus pool.")
            if spell.focus_cost > current_focus:
                raise ToolError(
                    f"Not enough Focus for {spell.name}: costs {spell.focus_cost}, you have {current_focus}."
                )

        # Resonance generated by this cast. The catalog's designed per-spell value is the
        # SSOT (decision resonance-by-source-ssot): 12/58 spells intentionally deviate from
        # the source*focus formula (power spells tear the Veil harder, gentle ones less), so
        # cast reads spell.resonance_by_source[source]. The formula is the fallback only when
        # a spell carries no entry for its source (in-code builds; every catalog row has one),
        # which is also where a primal-without-terrain build still fails loud (Focus untouched).
        generated = spell.resonance_by_source.get(spell.source)
        if generated is None:
            try:
                generated = resonance.calculate_resonance_generated(
                    spell.focus_cost, spell.source, terrain=_DEFAULT_TERRAIN
                )
            except ValueError as e:
                raise ToolError(f"Cannot cast {spell.name}: {e}") from e

        if spell.focus_cost > 0:
            await persistence_mod.update_player_resources(player_id, focus=current_focus - spell.focus_cost, conn=conn)

        # Persist the new total BEFORE touching the in-memory SSOT, so a failed
        # write/commit rolls back Focus AND leaves session.resonance untouched.
        new_resonance = session.resonance.current + generated
        if generated > 0:
            await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)

    # Transaction committed cleanly — now sync the in-memory SSOT to the persisted value.
    session.resonance.current = new_resonance
    state = resonance.get_resonance_state(session.resonance.current)
    # Push the new qualitative state to the HUD only when resonance actually moved —
    # a cantrip (generated == 0) leaves the state unchanged, so it pushes nothing (AC6).
    if generated > 0:
        await resonance_events_mod.publish_resonance_changed(session)
    packet = {
        "narration_cue": spell.narration_cue,
        "audio_cue": spell.audio_cue,
        "effect": spell.mechanics,
        "state": state,
        "resonance_generated": generated,
        "resonance_modifiers": resonance.get_state_modifiers(state),
    }
    # Cantrips scale their base damage with character level (story-003); fixed-cost
    # spells carry their damage in `mechanics`, so no scaled dice for them.
    if spell.spell_tier == "cantrip":
        packet["damage_dice"] = leveling_mod.cantrip_damage_dice(player.get("level", 1))
    return json.dumps(packet)
