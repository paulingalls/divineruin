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
resonance_mutations_mod/resonance_events_mod/spells_mod/resonance/leveling_mod, the M3.2
echo/ward mods veil_ward/hollow_echo/dice_mod/echo_events_mod, plus the M3.4 racial_mod/
concentration_mutations_mod) for test mocking, a single db.transaction() block, and
ToolError for every user-facing failure.

M3.4 racial Resonance (story-006): the cast reads the caster's race (players.data) and
composes three prior pure primitives — Korath -1 primal generation
(resonance.apply_primal_reduction), the Thessyn +1 Flickering threshold
(get_resonance_state flickering_bonus), and the Vaelti Hollow Echo advantage
(resolve_hollow_echo advantage_roll) — and sets/ends single-active concentration
(db_mutations_concentration) on a concentration cast. The engines stay untouched; this is
pure composition.

Terrain note: every catalog spell (primal included) carries a designed
resonance_by_source baseline, so casts no longer depend on terrain — a primal
non-cantrip casts via its catalog baseline. The fallback formula
(calculate_resonance_generated) only reaches the terrain lookup for an in-code
primal build that carries no resonance_by_source entry, and since no runtime
location->terrain map exists yet (terrain defaults to "normal"), that one path
still fails loud as a ToolError until terrain wiring lands. The same missing
terrain map means the Korath -1 (spec gates it on earth/stone contact) applies on
race+source alone — terrain gating is deferred, not modelled here.
"""

import json
import logging
from dataclasses import asdict

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import db
import db_mutations_concentration
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
import veil_ward as veil_ward_mod
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
    veil_ward=veil_ward_mod,
    hollow_echo=hollow_echo_mod,
    dice_mod=dice,
    echo_events_mod=hollow_echo_events,
    racial_mod=racial_resonance,
    concentration_mutations_mod=db_mutations_concentration,
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
        # The caster's race drives the M3.4 racial Resonance interactions (Korath/Thessyn/Vaelti
        # below). A player with no race set takes no racial branch.
        race = player.get("race")

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

        # Korath Earth-anchored (spec 254-260): a Korath's primal cast generates -1 Resonance
        # (floor 0), the earth absorbing the Veil disturbance. Applied to the base generation
        # BEFORE the ward halving, and before accrual so a floored 0 flows through the generated>0
        # write/publish gates below (no resonance write, no HUD push). The spec's earth/stone
        # terrain condition is deferred — no runtime terrain map exists yet (cast already defaults
        # terrain to "normal", see the module docstring), so the reduction gates on race+source only.
        if race == "korath" and spell.source == "primal" and generated > 0:
            reduction = racial_mod.get_racial_resonance_modifier("korath", "primal_reduction")
            generated = resonance.apply_primal_reduction(generated, reduction)

        # An active Veil Ward halves the Resonance the cast generates (round down, spec
        # magic.md:197) — so a warded caster reaches Overreach (and Hollow Echoes) less often.
        # Focus cost is NOT halved (the ward dampens generation, not the spell's cost).
        ward_active = session.veil_ward.active
        if ward_active and generated > 0:
            generated = veil_ward.halve_generation(generated)

        if spell.focus_cost > 0:
            await persistence_mod.update_player_resources(player_id, focus=current_focus - spell.focus_cost, conn=conn)

        # Persist the new total BEFORE touching the in-memory SSOT, so a failed
        # write/commit rolls back Focus AND leaves session.resonance untouched.
        new_resonance = session.resonance.current + generated
        if generated > 0:
            await resonance_mutations_mod.update_player_resonance(player_id, new_resonance, conn=conn)

        # Casting a concentration spell starts concentration on it and ends any prior one. The
        # single players.data{concentration,spell_id} slot means this one write IS the "prior
        # ends" (single-active concentration, spec). Persisted inside the txn so a rollback reverts
        # it with Focus/Resonance. A non-concentration cast never touches concentration.
        if spell.concentration:
            await concentration_mutations_mod.update_player_concentration(player_id, spell_id, conn=conn)

    # Transaction committed cleanly — now sync the in-memory SSOT to the persisted value.
    session.resonance.current = new_resonance
    if spell.concentration:
        session.concentration.spell_id = spell_id
    # Thessyn Deep Adaptation (spec 270-276) shifts the Flickering band up by +1, so a Thessyn
    # holds Overreach off a point longer. The bonus lives on the ResonanceTrack so EVERY state
    # derivation (the packet below, the publish_resonance_changed HUD push, any later reader)
    # shares one value and cannot diverge — DM voice and HUD always agree. Applied by race here;
    # the spec's "10+ sessions" gate needs a player session counter that does not exist yet
    # (deferred, concern 70434a66417c).
    session.resonance.flickering_bonus = (
        racial_mod.get_racial_resonance_modifier("thessyn", "flickering_threshold_bonus") if race == "thessyn" else 0
    )
    state = session.resonance.state
    # Push the new qualitative state to the HUD only when resonance actually moved —
    # a cantrip (generated == 0) leaves the state unchanged, so it pushes nothing (AC6).
    if generated > 0:
        await resonance_events_mod.publish_resonance_changed(session)
    # An active ward folds its -1 damage die / -1 DC (spec magic.md:199-200) into the net
    # combat modifiers the DM applies; the negative net is the ward's deliberate power-for-safety
    # cost. get_state_modifiers returns a fresh dict, so this never mutates the shared table.
    modifiers = resonance.get_state_modifiers(state)
    if ward_active:
        modifiers["damage_dice"] += veil_ward.WARD_DAMAGE_DIE_PENALTY
        modifiers["dc"] += veil_ward.WARD_DC_PENALTY
    packet = {
        "narration_cue": spell.narration_cue,
        "audio_cue": spell.audio_cue,
        "effect": spell.mechanics,
        "state": state,
        "resonance_generated": generated,
        "resonance_modifiers": modifiers,
        "ward_active": ward_active,
    }
    # At Overreach the Veil tears: auto-roll a d20 Hollow Echo (spec magic.md:167-185). An
    # active ward adds +4 to the roll (milder result). The band is returned for the DM to
    # narrate the consequence and pushed to the client's dramatic-dice overlay.
    if state == "overreach":
        roll = dice_mod.roll("d20").total
        # Vaelti Hyper-awareness (spec 246-252): advantage on the Hollow Echo save — roll a second
        # d20 and take the better, shifting the result milder. The 1-round advance warning is a
        # separate deferred-event hook with no consumer yet (concern 7e812546829a).
        advantage_roll = None
        if race == "vaelti" and racial_mod.get_racial_resonance_modifier("vaelti", "echo_save_advantage"):
            advantage_roll = dice_mod.roll("d20").total
        echo = hollow_echo.resolve_hollow_echo(
            roll,
            session.resonance.current,
            ward_bonus=veil_ward.WARD_ECHO_BONUS if ward_active else 0,
            advantage_roll=advantage_roll,
        )
        packet["hollow_echo"] = {"band": echo.band, "name": echo.name, "effect": echo.effect}
        await echo_events_mod.publish_hollow_echo(session, echo)
    # Cantrips scale their base damage with character level (story-003); fixed-cost
    # spells carry their damage in `mechanics`, so no scaled dice for them.
    if spell.spell_tier == "cantrip":
        packet["damage_dice"] = leveling_mod.cantrip_damage_dice(player.get("level", 1))
    return json.dumps(packet)
