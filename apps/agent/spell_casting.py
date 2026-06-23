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

import inspect
import json
import logging
from dataclasses import asdict, dataclass
from typing import cast

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
import vaelti_echo_warning
import veil_ward as veil_ward_mod
from db_errors import db_tool
from resource_costs import gate_pool
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


# Sentinel for CastResult.concentration_spell_id: a non-concentration cast never touches
# concentration, which must be distinguishable from "end concentration" (None is a valid
# concentration_spell_id). _UNCHANGED means "this cast did not touch concentration".
_UNCHANGED = object()


@dataclass(frozen=True)
class CastResult:
    """The outcome of resolving one cast, returned by ``_resolve_cast`` for the caller to commit.

    ``_resolve_cast`` is in-memory-PURE: it persists via the passed ``conn`` but never mutates the
    session's resonance/concentration SSOT, so a rolled-back caller tx leaves the session pristine.
    The caller syncs these post-commit from this result and then flushes ``events`` (deferred so a
    rollback leaks no client event).

    ``new_resonance`` is the value persisted this cast, or ``None`` when nothing was generated
    (no resonance write — a cantrip or a floored-to-0 reduction). ``concentration_spell_id`` is the
    started spell id, or the ``_UNCHANGED`` sentinel when the cast never touched concentration.
    """

    packet: dict
    new_resonance: int | None
    concentration_spell_id: object
    generated: int
    events: list

    async def flush_events(self) -> None:
        """Emit the deferred client events in order. Call ONLY after the caller's tx commits.

        Each entry is a zero-arg callable; sync ones (the bus-only Vaelti warning) return None,
        async ones (resonance/echo publishes) return a coroutine that is awaited."""
        for emit in self.events:
            result = emit()
            if inspect.isawaitable(result):
                await result


def _gate_spell(player: dict, spell_id: str, *, spells_mod=spells):
    """Resolve a spell and assert the player can afford its Focus, or raise ToolError.

    Shared by ``_resolve_cast`` and the in-combat Focus pre-validation (combat_turn, story-007) so
    both reject an unknown spell or unaffordable cast IDENTICALLY — and, in combat, before any write
    (AC2). Pure (no I/O): the caller supplies the already-fetched player row. Cantrips (focus_cost 0)
    always pass. Returns the resolved Spell."""
    try:
        spell = spells_mod.get_spell(spell_id)
    except ValueError as e:
        raise ToolError(str(e)) from e
    # Fail-loud Focus gate (pure); the deduct happens later in _resolve_cast after the
    # Resonance math, so the returned post-deduct value is unused here.
    gate_pool(player, "focus", spell.focus_cost, label=spell.name)
    return spell


# Revival spells refused on a Hollow-killed corpse (M4.4 story-007; content/spells.json
# divine_revivify "Doesn't work on Hollow-killed"). A set so other revival spells extend here.
REVIVAL_SPELL_IDS = frozenset({"divine_revivify"})


def revivify_refused(character_data: dict) -> bool:
    """Whether a revival spell must be refused for this character: True when it is Hollow-killed
    (M4.4 story-007). Pure + target-agnostic — the spell-targeting milestone reuses it unchanged,
    rerouting the call from the caster row to the target row."""
    return bool(character_data.get("hollow_killed"))


@function_tool()
@db_tool
async def cast_spell(
    context: RunContext[SessionData],
    spell_id: str,
    target_id: str | None = None,
) -> str:
    """Cast a spell by its id (e.g. 'arcane_bolt'). Call when the caster casts a
    known spell. Validates and deducts the spell's Focus cost (rejecting if the
    caster can't afford it), builds the hidden Resonance the cast generates, and
    returns the effect, narration_cue, and audio_cue to voice plus the resulting
    Resonance state and its combat modifiers. Cantrips are free and scale damage
    with level — the packet's damage_dice carries the scaled dice.

    Pass target_id when the spell is aimed at another entity — a fallen corpse for
    a revival spell, an ally to buff, an object or area. Omit it (the default) for
    a self-cast. A revival spell is refused if its target is Hollow-killed."""
    return await _cast_spell_impl(context, spell_id, target_id=target_id)


async def _cast_spell_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    target_id: str | None = None,
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
    vaelti_warning_mod=vaelti_echo_warning,
    concentration_mutations_mod=db_mutations_concentration,
) -> str:
    """Out-of-combat cast entry. Opens its own transaction, delegates the cast to the shared
    ``_resolve_cast`` core, then syncs the in-memory SSOT and flushes the deferred events
    post-commit. In-combat casting flows through declare_phase/resolve_phase instead (story-007)."""
    context.disallow_interruptions()
    _validate_id(spell_id, "spell_id")
    session: SessionData = context.userdata
    logger.info("cast_spell called: spell=%s player=%s", spell_id, session.player_id)

    async with db_mod.transaction() as conn:
        result = await _resolve_cast(
            session,
            spell_id,
            conn=conn,
            target_id=target_id,
            queries_mod=queries_mod,
            persistence_mod=persistence_mod,
            resonance_mutations_mod=resonance_mutations_mod,
            resonance_events_mod=resonance_events_mod,
            spells_mod=spells_mod,
            resonance=resonance,
            leveling_mod=leveling_mod,
            veil_ward=veil_ward,
            hollow_echo=hollow_echo,
            dice_mod=dice_mod,
            echo_events_mod=echo_events_mod,
            racial_mod=racial_mod,
            vaelti_warning_mod=vaelti_warning_mod,
            concentration_mutations_mod=concentration_mutations_mod,
        )

    # Transaction committed cleanly — sync the in-memory SSOT to the persisted values, then release
    # the deferred client events. A rolled-back tx skips this (the `async with` re-raises), so the
    # session stays pristine and no event fires.
    if result.new_resonance is not None:
        session.resonance.current = result.new_resonance
    if result.concentration_spell_id is not _UNCHANGED:
        session.concentration.spell_id = cast("str | None", result.concentration_spell_id)
    await result.flush_events()
    return json.dumps(result.packet)


async def _resolve_cast(
    session: SessionData,
    spell_id: str,
    *,
    conn,
    target_id: str | None = None,
    player: dict | None = None,
    suppress_resonance_changed: bool = False,
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
    vaelti_warning_mod=vaelti_echo_warning,
    concentration_mutations_mod=db_mutations_concentration,
) -> CastResult:
    """Resolve ONE cast against the DB using the caller's ``conn`` (opens no transaction of its own),
    shared by ``cast_spell`` (out-of-combat) and the in-combat ABILITY packet (story-007).

    In-memory-PURE: it persists Focus/Resonance/concentration via ``conn`` but never mutates
    ``session.resonance`` / ``session.concentration`` — the caller syncs those post-commit from the
    returned ``CastResult``, so a rolled-back caller tx leaves the session pristine (``scratch_guard``
    does not cover resonance). All client events are DEFERRED into ``result.events`` for the caller to
    flush after commit (a rollback drops them, leaking nothing).

    ``player`` lets the caller pass a pre-fetched for-update row (the phase path locks it once for
    Focus pre-validation); when ``None`` the cast fetches it. ``suppress_resonance_changed`` omits the
    cast's own RESONANCE_CHANGED push — in combat the phase WRAP push is the single authoritative HUD
    update, so the ability must not double-emit."""
    _validate_id(spell_id, "spell_id")
    # Validate the explicit target id the same way as spell_id, on the shared core so BOTH the
    # out-of-combat cast and the in-combat ABILITY path are guarded once (concern 8816cdffb757).
    if target_id is not None:
        _validate_id(target_id, "target_id")
    player_id = session.player_id

    if player is None:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Unknown player: {player_id}")

    # Revivify gate (M4.4 story-007, rerouted M11): a revival spell cannot reach a Hollow-killed
    # corpse. The refusal keys on the TARGET row — the resolved target_id when given, else the caster
    # (self-cast). Only a revival spell validates the target; a non-revival targeted cast is
    # DM-narrated and skips the fetch (assumption eabd919bf1ca). Refused before any Focus/Resonance
    # write. revivify_refused stays pure + target-agnostic, reused unchanged.
    if spell_id in REVIVAL_SPELL_IDS:
        if target_id is not None and target_id != player_id:
            gate_row = await queries_mod.get_player(target_id, conn=conn)
            if gate_row is None:
                raise ToolError(f"Unknown target: {target_id}")
        else:
            gate_row = player
        if revivify_refused(gate_row):
            raise ToolError(f"{spell_id} cannot reach the corpse — it is Hollow-killed.")
    # The caster's race drives the M3.4 racial Resonance interactions (Korath/Thessyn/Vaelti
    # below). A player with no race set takes no racial branch.
    race = player.get("race")

    # Resolve the spell + Focus gate FIRST — reject before any write so an unaffordable cast deducts
    # nothing (AC1 out-of-combat; in combat the phase pre-validates this same gate before the loop so
    # nothing else is clobbered). Cantrips (focus_cost 0) always pass.
    spell = _gate_spell(player, spell_id, spells_mod=spells_mod)
    current_focus = (player.get("focus") or {}).get("current", 0)

    # Resonance generated by this cast. The catalog's designed per-spell value is the SSOT (decision
    # resonance-by-source-ssot): a subset of catalog spells intentionally deviate from the
    # source*focus formula (power spells tear the Veil harder, gentle ones less), so cast reads
    # spell.resonance_by_source[source]. The formula is the fallback only when a spell carries no
    # entry for its source (in-code builds; every catalog row has one), which is also where a
    # primal-without-terrain build still fails loud (Focus untouched).
    generated = spell.resonance_by_source.get(spell.source)
    if generated is None:
        try:
            generated = resonance.calculate_resonance_generated(
                spell.focus_cost, spell.source, terrain=_DEFAULT_TERRAIN
            )
        except ValueError as e:
            raise ToolError(f"Cannot cast {spell.name}: {e}") from e

    # Korath Earth-anchored (spec 254-260): a Korath's primal cast generates -1 Resonance (floor 0),
    # the earth absorbing the Veil disturbance. Applied to the base generation BEFORE the ward
    # halving, and before accrual so a floored 0 flows through the generated>0 write/publish gates
    # below (no resonance write, no HUD push). The spec's earth/stone terrain condition is deferred —
    # no runtime terrain map exists yet — so the reduction gates on race+source only.
    if race == "korath" and spell.source == "primal" and generated > 0:
        reduction = racial_mod.get_racial_resonance_modifier("korath", "primal_reduction")
        generated = resonance.apply_primal_reduction(generated, reduction)

    # An active Veil Ward halves the Resonance the cast generates (round down, spec magic.md:197) —
    # so a warded caster reaches Overreach (and Hollow Echoes) less often. Focus cost is NOT halved
    # (the ward dampens generation, not the spell's cost).
    ward_active = session.veil_ward.active
    if ward_active and generated > 0:
        generated = veil_ward.halve_generation(generated)

    if spell.focus_cost > 0:
        await persistence_mod.update_player_resources(player_id, focus=current_focus - spell.focus_cost, conn=conn)

    # Per-round decay (cast-paced, story-010): a real cast first sheds one round of standing Resonance
    # — base 1/round, +1 for a Human (Adaptive Resonance) => 2/round — before this cast's generation
    # lands. apply_resonance_decay floors at 0. A cantrip (generated 0) skips decay, leaving the state
    # untouched (AC6). IN COMBAT this cast-paced shed is SUPPRESSED (story-007) via session.in_combat:
    # the phase WRAP beat is the canonical decay clock (decision resonance-decay-phase-canonical), so
    # an in-combat cast only GENERATES — the WRAP applies the single per-phase decay.
    should_decay = generated > 0 and not session.in_combat
    decay_modifier = 0
    if race == "human":
        decay_modifier = racial_mod.get_racial_resonance_modifier("human", "decay_bonus")
    base_resonance = (
        resonance.apply_resonance_decay(session.resonance.current, decay_modifier)
        if should_decay
        else session.resonance.current
    )

    # The post-cast total. Persist it via conn but keep it LOCAL — the caller syncs session.resonance
    # post-commit, so a rollback leaves the in-memory track untouched. new_resonance is None when
    # nothing generated (no write), so the caller leaves the standing value alone.
    effective_resonance = base_resonance + generated
    new_resonance = effective_resonance if generated > 0 else None
    if generated > 0:
        await resonance_mutations_mod.update_player_resonance(player_id, effective_resonance, conn=conn)

    # Casting a concentration spell starts concentration on it and ends any prior one (the single
    # players.data{concentration,spell_id} slot makes this one write the "prior ends"). Persisted via
    # conn; the started spell id is RETURNED for the caller to sync in-memory post-commit. A
    # non-concentration cast never touches concentration (returns the _UNCHANGED sentinel).
    concentration_spell_id: object = _UNCHANGED
    if spell.concentration:
        await concentration_mutations_mod.update_player_concentration(player_id, spell_id, conn=conn)
        concentration_spell_id = spell_id

    # State is derived from the LOCAL post-cast value (NOT session.resonance.current, which is unsynced
    # until the caller commits) via the pure get_resonance_state, so nothing sticks on rollback.
    # flickering_bonus is hydrated + GATED at session-init (story-004) and session-stable — read it
    # from the track so every derivation (packet, HUD, cast) shares one value.
    state = resonance.get_resonance_state(effective_resonance, flickering_bonus=session.resonance.flickering_bonus)

    # Defer every client event so the caller flushes them post-commit (rollback-safe). The cast's own
    # RESONANCE_CHANGED is omitted when suppressed (in combat the WRAP push is authoritative) and when
    # nothing generated (a cantrip leaves the state unchanged — AC6).
    events: list = []
    if generated > 0 and not suppress_resonance_changed:
        events.append(lambda: resonance_events_mod.publish_resonance_changed(session))

    # An active ward folds its -1 damage die / -1 DC (spec magic.md:199-200) into the net combat
    # modifiers. get_state_modifiers returns a fresh dict, so this never mutates the shared table.
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
    # Carry the explicit target into the packet for the DM to voice (corpse/ally/object/area).
    # Additive — a self-cast (target_id None) leaves the packet shape untouched.
    if target_id is not None:
        packet["target_id"] = target_id
    # At Overreach the Veil tears: auto-roll a d20 Hollow Echo (spec magic.md:167-185). An active ward
    # adds +4 to the roll (milder result). The echo resolves against the LOCAL effective_resonance
    # (not the unsynced session value).
    if state == "overreach":
        roll = dice_mod.roll("d20").total
        # Vaelti Hyper-awareness (spec 246-252): advantage on the Hollow Echo save (a second d20, take
        # the better -> milder band) AND a 1-round advance warning. The warning is a bus-only deferred
        # event the background process voices a heartbeat before the echo lands (story-009 consumer).
        advantage_roll = None
        if race == "vaelti" and racial_mod.get_racial_resonance_modifier("vaelti", "echo_save_advantage"):
            advantage_roll = dice_mod.roll("d20").total
            events.append(lambda: vaelti_warning_mod.publish_vaelti_echo_warning(session))
        echo = hollow_echo.resolve_hollow_echo(
            roll,
            effective_resonance,
            ward_bonus=veil_ward.WARD_ECHO_BONUS if ward_active else 0,
            advantage_roll=advantage_roll,
        )
        packet["hollow_echo"] = {"band": echo.band, "name": echo.name, "effect": echo.effect}
        events.append(lambda: echo_events_mod.publish_hollow_echo(session, echo))
    # Cantrips scale their base damage with character level (story-003); fixed-cost spells carry their
    # damage in `mechanics`, so no scaled dice for them.
    if spell.spell_tier == "cantrip":
        packet["damage_dice"] = leveling_mod.cantrip_damage_dice(player.get("level", 1))

    return CastResult(
        packet=packet,
        new_resonance=new_resonance,
        concentration_spell_id=concentration_spell_id,
        generated=generated,
        events=events,
    )
