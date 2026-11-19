"""Once-per-actor turn effects carried by the committed combat snapshot."""

from dataclasses import replace
from functools import partial

import check_resolution_save
import combat_spatial
import dice
import spells
import ward_resolution
from combat_enemy_active import heal
from combat_fate_rolls import packet_save
from condition_produce import resolve_effective_targets


def mark_radiant(target, action, result):
    if target.regeneration is None or result.damage <= 0 or not getattr(result, "hit", True):
        return
    bonus, rider = getattr(result, "bonus_damage", 0), getattr(result, "rider_damage", 0)
    components = action.get("damage_components")
    radiant = (
        any(c["damage_type"] == "radiant" and c["damage"] > 0 for c in components)
        if components is not None
        else result.damage_type == "radiant"
        and result.damage - bonus - rider - getattr(result, "synergy_damage", 0) > 0
    )
    if (
        radiant
        or (bonus > 0 and result.bonus_damage_type == "radiant")
        or (rider > 0 and result.rider_damage_type == "radiant")
    ):
        target.radiant_suppression_pending = True


def living(actor):
    return actor.hp_current > 0 and not actor.is_fallen and not actor.is_dead


def absorb_spell(state, caster, declaration, packet):
    """Consume only living Veilrender recipients; caster bookkeeping has already run."""
    spell = spells.get_spell(declaration.action)
    profile = spell.combat_damage
    if (
        profile
        and profile["resolution"] != "deferred"
        and any(c["damage_type"] == "radiant" for c in profile["components"])
    ):
        return declaration
    targets = resolve_effective_targets(declaration.target_ids, declaration.target_id, self_value=caster.id, dedup=True)
    remaining, absorbed = [], []
    for target_id in targets:
        target = state.get_participant(target_id)
        if target is None or target.creature_id != "hollow_veilrender" or not living(target):
            remaining.append(target_id)
            continue
        absorbed.append(
            {
                "effect": "Absorb Magic",
                "target_id": target_id,
                "healed": heal(target, 3 * spell.focus_cost),
                "hp_current": target.hp_current,
            }
        )
    if not absorbed:
        return declaration
    packet["absorbed"] = absorbed
    cue = " ".join(
        f"Absorb Magic: {a['target_id']} absorbed the spell; it had no effect on this recipient. "
        f"Regained {a['healed']} HP, now {a['hp_current']} HP."
        for a in absorbed
    )
    if remaining:
        packet["narration_cue"] += " " + cue
        packet["effect"] += " Apply only to: " + ", ".join(remaining) + ". " + cue
        return replace(declaration, target_id=None, target_ids=remaining)
    for key in ("condition_applied", "condition_targets", "damage_result", "deferred"):
        packet.pop(key, None)
    packet["effect"] = packet["narration_cue"] = cue
    return None


async def turn_start(
    session, state, actor, *, conn=None, mutations, queries, concentration_break_mod, sink=None, progress=None, **unused
):
    """Regeneration and the Corruption Field save at ``actor``'s turn start, once per round.

    With ``progress`` the field save (and its damage receipt) may be Zhael-held: None is returned
    while a choice is pending, and the resumed call finishes from the effects kept in its steps."""
    from combat_damage import apply_attack_result
    from combat_damage_results import AutomaticDamageResult

    sources = [p for p in state.participants if p.corruption_field is not None and living(p)]
    steps = progress.steps if progress is not None else {}
    effects = steps.get("effects")
    if effects is None:
        if actor is None or actor.veilrender_turn_round == state.round_number or not living(actor):
            return []
        if not sources and actor.regeneration is None:
            return []
        effects = await _regenerate(session, state, actor, conn)
        if actor.hollow is not None or actor.type == "temporary_hollowed":
            return effects
        if progress is not None:
            steps["effects"] = effects
    spatial = combat_spatial.require_spatial(state)
    done = {e["source_id"] for e in effects if e["effect"] == "corruption_field"}
    for source in sources:
        if source.id in done or not combat_spatial.inside(
            combat_spatial.position(spatial, source.id),
            combat_spatial.position(spatial, actor.id),
            source.hollow["corruption_aura"],
        ):
            continue
        spec = source.corruption_field
        scope = progress.scope(source.id) if progress is not None else None
        effect = scope.steps.get("effect") if scope is not None else None
        if effect is None:
            save = await packet_save(
                scope,
                session,
                actor.id,
                "Corruption Field",
                partial(
                    check_resolution_save.roll_participant_save,
                    actor,
                    spec["save"],
                    spec["dc"],
                    "Corruption Field",
                    bonus_dice_eligible=False,
                ),
            )
            if save is None:
                return None
            effect = {
                "actor_id": actor.id,
                "source_id": source.id,
                "effect": "corruption_field",
                "save_success": save.success,
                "save_dc": spec["dc"],
            }
            if scope is not None:
                scope.steps["effect"] = effect
        if not effect["save_success"]:
            resumed = scope is not None and "damage_receipt" in scope.steps
            landed = await apply_attack_result(
                session,
                source,
                {"name": "Corruption Field"},
                actor,
                None if resumed else AutomaticDamageResult(dice.roll(spec["damage"]).total, spec["damage_type"]),
                actor.ac,
                mutations=mutations,
                queries=queries,
                concentration_break_mod=concentration_break_mod,
                combat_state=state,
                conn=conn,
                sink=sink,
                publish_roll=False,
                progress=scope,
            )
            if scope is not None and scope.paused:
                return None
            effect.update(landed)
        if scope is not None:
            scope.steps.pop("effect")
        effects.append(effect)
        if not living(actor):
            break
    steps.pop("effects", None)
    return effects


async def _regenerate(session, state, actor, conn):
    ward = None
    if actor.regeneration is not None:
        if conn is None:
            raise ValueError("Veilrender turn requires a connection for current ward coverage")
        ward = await ward_resolution.resolve_scope_ward(session, conn=conn, combat_state=state)
    actor.veilrender_turn_round = state.round_number
    effects = []
    if actor.regeneration is not None:
        radiant = actor.radiant_suppression_pending
        suppressed = ward is not None or radiant
        actor.radiant_suppression_pending = False
        spec = actor.regeneration
        effect = {
            "actor_id": actor.id,
            "effect": "regeneration",
            "suppressed": suppressed,
            "causes": (["ward"] if ward is not None else []) + (["radiant"] if radiant else []),
            "cues": [],
        }
        if suppressed and not actor.regeneration_suppressed:
            effect["cues"].append(spec["suppressed_cue"])
        elif not suppressed and actor.regeneration_suppressed:
            effect["cues"].append(spec["resumed_cue"])
        actor.regeneration_suppressed = suppressed
        effect["healed"] = 0 if suppressed else heal(actor, spec["hp"])
        if effect["healed"]:
            effect["cues"].append(spec["narration_cue"])
        effects.append(effect)
    return effects
