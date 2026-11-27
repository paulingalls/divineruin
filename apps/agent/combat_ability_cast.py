"""Resolve in-combat ability declarations backed by spells."""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

import architect_reaction
import combat_enhancers
import combat_hollow_resonance
import combat_spell_damage
import combat_spell_heal
import combat_turn_undead
import combat_veilrender
import combat_voice_rules
import combat_yield
import concealment
import db_queries
import spell_casting
import wild_shape
from combat_condition_landing import land_condition_on_participants
from combat_structures import blocked_reason, line_blocker
from condition_sources import DeliveryRefused
from session_data import CombatParticipant, SessionData
from spell_condition_cleanse import GREATER_RESTORATION, CleanseRefused

if TYPE_CHECKING:
    from spell_casting import CastResult


@dataclass
class AbilityCastOutcome:
    """Side-channel carrying the in-loop ABILITY casts' ``CastResult``s back to the phase loop.

    Each party member may declare one ability per phase (M14 story-004), so results are keyed by the
    caster's participant id (== player_id). The loop reads ``results`` post-commit to seed each
    member's WRAP resonance, flush their deferred client events, and push per-member HUD state — all
    of which must happen after the phase tx commits (story-007). ``results`` stays empty when no
    ability resolved. Concentration is synced IN-LOOP by ``_resolve_ability_packet`` (not here)."""

    results: dict[str, "CastResult"] = field(default_factory=dict)


async def _resolve_ability_packet(
    session: SessionData,
    attacker: CombatParticipant,
    decl,
    *,
    state,
    cast_resolver,
    conn,
    player: dict | None,
    cast_outcome: AbilityCastOutcome,
    damage_deps=None,
    progress=None,
) -> dict:
    """Cast once, then land spell damage and conditions on effective recipients."""
    if attacker.type != "player":
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability resolution not yet implemented for non-player actors",
        }
    if not decl.action:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": "ability declaration missing an action",
        }

    import choir_encounter
    import still_encounter

    still_encounter.guard_declaration(state, attacker.id, decl)
    choir_encounter.guard_declaration(state, attacker.id, decl)
    caster = session.member_state(attacker.id)
    combat_voice_rules.guard_declaration(state, attacker, decl)
    import spells
    from choir_reaction import effective_declaration
    from combat_spell_recipients import select

    spell = spells.get_spell(decl.action)
    declared = decl
    cleanses = spell.id == GREATER_RESTORATION
    turns_undead = spell.id == combat_turn_undead.TURN_UNDEAD
    steps = progress.steps if progress is not None else {}
    shield_receipts = steps.setdefault("harmonic_shield_saves", [])
    shield = progress.scope("shield") if progress is not None else None
    deliveries = None
    selected = None
    recipient_profile = spell.combat_damage and spell.combat_damage.get("recipients")
    if (
        not cleanses
        and not recipient_profile
        and not turns_undead
        and "cast_packet" not in steps
        and (wall := line_blocker(state, attacker.id, decl.target_id))
    ):
        return {"actor_id": attacker.id, "resolved": False, "reason": blocked_reason(wall)}
    if recipient_profile or turns_undead:
        # Area recipients are frozen once, then each distinct recipient may redirect the spell (the
        # Choir's shield). A Zhael-held redirect save resumes here without re-selecting or re-rolling.
        selected = steps.get("selected")
        if selected is None:
            try:
                if turns_undead:
                    selected, steps["turn_refusals"] = combat_turn_undead.select(state, attacker)
                else:
                    selected = select(state, attacker, decl, spell)
            except DeliveryRefused as e:
                return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}
            if progress is not None:
                steps["selected"] = selected
        redirects = steps.setdefault("redirects", {})
        for target_id in dict.fromkeys(d["target_id"] for d in selected):
            if target_id in redirects:
                continue
            redirected = await effective_declaration(
                session,
                state,
                attacker,
                replace(decl, target_id=target_id, target_ids=None),
                progress=shield.scope(target_id) if shield is not None else None,
                receipts=shield_receipts,
            )
            if redirected is None:
                return {}
            redirects[target_id] = redirected.target_id
        deliveries = [
            {**d, "target_id": redirects[d["target_id"]]}
            for d in selected
            if not turns_undead or redirects[d["target_id"]] == d["target_id"]
        ]
    elif spell.heal is None and not cleanses:
        decl = await effective_declaration(session, state, attacker, decl, progress=shield, receipts=shield_receipts)
        if decl is None:
            return {}
    landing_intent, deliveries, interception = (
        (decl, deliveries, None)
        if cleanses
        else architect_reaction.spell_targets(state, attacker, decl, spell, deliveries, steps)
    )
    cast_packet = steps.get("cast_packet")
    if cast_packet is None:
        heal = spell.heal
        recipients = []
        if heal is not None:
            try:
                recipients = combat_spell_heal.combat_recipients(state, attacker, decl, spell, heal)
            except ValueError as e:
                return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}
        form = None
        if spell.wild_shape is not None:
            if player is None:
                raise RuntimeError(f"Missing locked player row for Wild Shape: {attacker.id}")
            queries = (damage_deps or {}).get("queries", db_queries)
            locked = await queries.get_player(attacker.id, conn=conn, for_update=True)
            if locked is None:
                raise RuntimeError(f"Missing locked player row for Wild Shape: {attacker.id}")
            form_id, _, stamina = wild_shape.gate(
                attacker, declared, locked, spell.wild_shape, stamina_cost=spell.wild_shape["stamina_cost"]
            )
            form = (form_id, await wild_shape.prepare_form(form_id, conn), stamina)
        try:
            result = await cast_resolver._resolve_cast(
                session,
                decl.action,
                conn=conn,
                caster=caster,
                player=player,
                combat_state=state,
                target_id=decl.target_id,
                target_ids=decl.target_ids,
                suppress_resonance_changed=True,
                **({"condition": decl.argument_type} if cleanses and decl.argument_type else {}),
            )
        except CleanseRefused as e:
            return {"actor_id": attacker.id, "resolved": False, "reason": str(e)}
        cast_outcome.results[attacker.id] = result
        if result.new_resonance is not None:
            combat_hollow_resonance.stage_total(state, attacker.id, result.new_resonance)
        # Later damage in this transaction must check the spell the caster just started concentrating on.
        if result.concentration_spell_id is not spell_casting._UNCHANGED:
            caster.concentration.spell_id = cast("str | None", result.concentration_spell_id)
        cast_packet = result.packet
        if form is not None:
            form_id, beast, stamina = form
            steps["wild_shape"] = await wild_shape.transform(
                attacker, form_id, beast, focus=None, stamina=stamina, conn=conn
            )
        if spell.hostile:
            steps["yield_receipt"] = combat_yield.end(attacker)
        if shield_receipts:
            cast_packet["harmonic_shield_saves"] = shield_receipts
        if heal is not None:
            if player is None:
                raise RuntimeError(f"Missing locked player row for healing caster {attacker.id}")
            await combat_spell_heal.land_combat_cast(
                state,
                spell,
                heal,
                attacker,
                recipients,
                caster_row=player,
                result=result,
                conn=conn,
            )
        # Veilrender Absorb Magic heals once per cast, so its landing is frozen with the cast packet.
        if deliveries is not None:
            effective_ids = list(dict.fromkeys(d["target_id"] for d in deliveries))
            landing = (
                combat_veilrender.absorb_spell(
                    state, attacker, replace(decl, target_id=None, target_ids=effective_ids), cast_packet
                )
                if effective_ids
                else None
            )
        else:
            landing = (
                combat_veilrender.absorb_spell(state, attacker, landing_intent, cast_packet)
                if landing_intent is not None
                else None
            )
        if interception is not None and landing is None:
            cast_packet["narration_cue"] = cast_packet["effect"] = interception["cue"]
            cast_packet.pop("damage_dice", None)
            cast_packet.pop("condition_applied", None)
        steps["cast_packet"] = cast_packet
        steps["landing"] = (
            None if landing is None else {"target_id": landing.target_id, "target_ids": landing.target_ids}
        )
    landing = None if steps["landing"] is None else replace(decl, **steps["landing"])
    if deliveries is not None:
        absorbed = {receipt["target_id"] for receipt in cast_packet.get("absorbed", [])}
        deliveries = [d for d in deliveries if d["target_id"] not in absorbed]
    if turns_undead:
        assert deliveries is not None and selected is not None
        await combat_turn_undead.land(
            session,
            state,
            attacker,
            spell,
            cast_packet,
            selected,
            steps["turn_refusals"],
            steps["redirects"],
            deliveries,
            interception,
            conn=conn,
            progress=progress.scope("turn_undead") if progress is not None else None,
            **{key: value for key, value in (damage_deps or {}).items() if key in ("queries", "sink")},
        )
        if progress is not None and progress.paused:
            return {}
    elif deliveries is not None or landing is not None:
        await combat_spell_damage.land(
            session,
            state,
            attacker,
            landing or decl,
            cast_packet,
            conn=conn,
            deliveries=deliveries,
            progress=progress.scope("spell_damage") if progress is not None else None,
            **(damage_deps or {}),
        )
        if progress is not None and progress.paused:
            return (
                {"actor_id": attacker.id, "resolved": False, "reactive_architecture": interception}
                if interception is not None
                else {}
            )
    if (spell.combat_damage or {}).get("resolution") == "attack" and "hit" not in cast_packet.get("damage_result", {}):
        cast_packet.pop("spell_attack_bonus", None)
        if "concealment" not in cast_packet:
            queries = (damage_deps or {}).get("queries", db_queries)
            if reveal := await concealment.reveal_attacker(attacker.id, conn=conn, queries=queries, ended_by="cast"):
                cast_packet["concealment"] = reveal
    # Beneficial-condition PRODUCER (M4.8 story-004), in-combat half: land the produced condition on the
    # recipients that remain after Absorb Magic. The mutation rides this phase's save_combat_state.
    cond_type = cast_packet.get("condition_applied")
    if cond_type and landing is not None:
        voiced = land_condition_on_participants(
            state, attacker, landing, cond_type, source=landing.action, packet=cast_packet
        )
        if voiced:
            cast_packet["condition_targets"] = voiced
        else:
            cast_packet.pop("condition_applied", None)
    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "action": decl.action,
        "cast": cast_packet,
        **steps.get("yield_receipt", {}),
    }
    if "wild_shape" in steps:
        summary["wild_shape"] = steps["wild_shape"]
    if interception is not None:
        summary["reactive_architecture"] = interception
    return _attach_riders(summary, attacker, decl)


def _attach_riders(summary: dict, attacker, decl) -> dict:
    riders = combat_enhancers.declaration_riders(attacker.enhancers, decl)
    if riders:
        summary["riders"] = riders
    return summary
