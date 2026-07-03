"""Spell casting tools for the DM agent (M3.3 story-004).

cast_spell is the real cast path: it validates a named spell, gates the caster's
Focus and deducts it, reads the Resonance the cast generates from the catalog's
designed per-spell resonance_by_source[source] (the SSOT, decision
resonance-by-source-ssot), accrues that onto the session's ResonanceTrack and
persists it, then returns an effect + narration_cue + audio_cue packet for the DM
to voice. The M3.1 rules engine (resonance.calculate_resonance_generated) is the
fallback only when a spell carries no entry for its source. Cantrips (focus_cost 0)
cost no Focus, generate 0 Resonance, and scale their damage via
leveling.cantrip_damage_dice(level). The read-only get_spell_info lookup lives in
spell_info_tools (it spends nothing and opens no transaction).

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
from dataclasses import dataclass
from typing import cast

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import ability_persistence
import condition_produce
import conditions
import db
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
from db_errors import db_tool
from party_state import PartyMember
from resource_costs import gate_pool
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# Default terrain for resonance generation. Only consulted for PRIMAL non-cantrips
# (see module docstring); a real location->terrain map is M3.4 work.
_DEFAULT_TERRAIN = "normal"


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

    Shared by ``_resolve_cast`` and the in-combat Focus pre-validation (combat_packet, story-007) so
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
    target_ids: list[str] | None = None,
) -> str:
    """Cast a spell by its id (e.g. 'arcane_bolt'). Call when the caster casts a
    known spell. Validates and deducts the spell's Focus cost (rejecting if the
    caster can't afford it), builds the hidden Resonance the cast generates, and
    returns the effect, narration_cue, and audio_cue to voice plus the resulting
    Resonance state and its combat modifiers. Cantrips are free and scale damage
    with level — the packet's damage_dice carries the scaled dice.

    Pass target_id when the spell is aimed at a single entity — a fallen corpse for
    a revival spell, an ally to buff, an object or area. Omit it (the default) for
    a self-cast. A revival spell is refused if its target is Hollow-killed.

    Pass target_ids (a list) when a multi-target spell names several allies at once —
    e.g. Bless on up to three companions. The spell's own cap is enforced (too many
    is refused). When a spell allows multiple, prefer target_ids over target_id."""
    return await _cast_spell_impl(context, spell_id, target_id=target_id, target_ids=target_ids)


async def _cast_spell_impl(
    context: RunContext[SessionData],
    spell_id: str,
    *,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
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
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    condition_produce_mod=condition_produce,
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
            target_ids=target_ids,
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
            conditions_mod=conditions_mod,
            conditions_mutations_mod=conditions_mutations_mod,
            condition_produce_mod=condition_produce_mod,
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
    caster: PartyMember | None = None,
    target_id: str | None = None,
    target_ids: list[str] | None = None,
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
    conditions_mod=conditions,
    conditions_mutations_mod=db_mutations_conditions,
    condition_produce_mod=condition_produce,
) -> CastResult:
    """Resolve ONE cast against the DB using the caller's ``conn`` (opens no transaction of its own),
    shared by ``cast_spell`` (out-of-combat) and the in-combat ABILITY packet (story-007).

    In-memory-PURE: it persists Focus/Resonance/concentration via ``conn`` but never mutates
    ``session.resonance`` / ``session.concentration`` — the caller syncs those post-commit from the
    returned ``CastResult``, so a rolled-back caller tx leaves the session pristine (``scratch_guard``
    does not cover resonance). All client events are DEFERRED into ``result.events`` for the caller to
    flush after commit (a rollback drops them, leaking nothing).

    ``caster`` is the PartyMember whose OWN pool (resonance/veil_ward/concentration) and player_id the
    cast reads and writes — defaulting to ``session.party.primary`` so the OOC path (which passes none)
    stays byte-identical to single-player. In multi-player combat the phase loop passes the declaring
    member, so a non-primary caster's Focus/Resonance/concentration land on THAT member, never the
    primary's (M14 story-004). ``session.resonance``/``session.veil_ward``/``session.concentration``
    delegate to the primary, so for a solo party ``caster`` == the primary is the same objects.

    ``player`` lets the caller pass a pre-fetched for-update row (the phase path locks it once for
    Focus pre-validation); when ``None`` the cast fetches it. ``suppress_resonance_changed`` omits the
    cast's own RESONANCE_CHANGED push — in combat the phase WRAP push is the single authoritative HUD
    update, so the ability must not double-emit."""
    caster = caster or session.party.primary
    _validate_id(spell_id, "spell_id")
    # Validate the explicit target id the same way as spell_id, on the shared core so BOTH the
    # out-of-combat cast and the in-combat ABILITY path are guarded once (concern 8816cdffb757).
    if target_id is not None:
        _validate_id(target_id, "target_id")
    if target_ids is not None:
        for tid in target_ids:
            _validate_id(tid, "target_id")
    player_id = caster.player_id

    locked_rows: dict[str, dict] | None = None
    if player is None:
        # OOC entry only (in-combat passes `player`, no OOC write): pre-lock the caster + any OOC
        # condition-producing targets via the shared deadlock-safe helper (story-005/008). An
        # unknown spell id here just yields produces_ooc=False — _gate_spell fails loud on it later.
        try:
            spell_def = spells_mod.get_spell(spell_id)
        except ValueError:
            spell_def = None
        produces_ooc = spell_def is not None and spell_def.applies_condition is not None and not session.in_combat
        locked_rows, player = await condition_produce_mod.lock_ooc_caster_and_targets(
            produces_ooc=produces_ooc,
            player_id=player_id,
            target_id=target_id,
            target_ids=target_ids,
            party_member_ids=session.party.member_ids,
            queries_mod=queries_mod,
            conn=conn,
        )
        assert player is not None  # guaranteed by lock_ooc_caster_and_targets or it raises

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
    # Multi-target normalization + cap (M4.8 story-007): reject both-args / empty / over-cap and
    # dedup BEFORE any Focus/Resonance write, so an invalid cast deducts nothing (same gate-first rule
    # as affordability). normalize_target_list is the targeting SSOT; convert its ValueError to a
    # DM-narratable ToolError. Rejecting an uncapped (single-target-only) spell here also closes the
    # revival Hollow-gate bypass — a revival spell has no max_targets, so target_ids on it is refused.
    if target_ids is not None:
        try:
            target_ids = spells_mod.normalize_target_list(spell, target_id, target_ids)
        except ValueError as e:
            raise ToolError(str(e)) from e
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
    ward_active = caster.veil_ward.active
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
        resonance.apply_resonance_decay(caster.resonance.current, decay_modifier)
        if should_decay
        else caster.resonance.current
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
    state = resonance.get_resonance_state(effective_resonance, flickering_bonus=caster.resonance.flickering_bonus)

    # Defer every client event so the caller flushes them post-commit (rollback-safe). The cast's own
    # RESONANCE_CHANGED is omitted when suppressed (in combat the WRAP push is authoritative) and when
    # nothing generated (a cantrip leaves the state unchanged — AC6).
    events: list = []
    if generated > 0 and not suppress_resonance_changed:
        events.append(
            lambda: resonance_events_mod.publish_resonance_changed(
                session, resonance_track=caster.resonance, caster_id=caster.player_id
            )
        )

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

    # Beneficial-condition producer (M4.8 story-004/005/007). In combat the participant is the SSOT
    # (combat_ability applies on the working state); OOC the shared condition_produce helper lands the
    # condition on each resolved target's players.data, AFTER the Focus/Resonance/revivify gates so a
    # refused cast produces nothing. condition_targets names the blessed allies for per-ally narration.
    if spell.applies_condition is not None:
        if session.in_combat:
            packet["condition_applied"] = spell.applies_condition  # combat applies + confirms on the participant
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
    )
