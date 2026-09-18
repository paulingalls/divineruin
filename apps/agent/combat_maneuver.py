"""Stand and shove resolution for combat maneuver declarations."""

import random

import combat_grapple
import conditions
from combat_condition_landing import _land_condition_on_one
from condition_restrictions import declaration_costs
from rules_engine import attribute_modifier


def resolve_maneuver(state, attacker, decl, *, rng=None) -> dict:
    roller = rng or random
    target = state.get_participant(decl.target_id)
    if target is None:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"target '{decl.target_id}' not found",
        }
    if target.is_fallen:
        return {
            "actor_id": attacker.id,
            "resolved": False,
            "declaration_type": str(decl.type),
            "reason": f"{target.name} already fell",
        }
    costs = declaration_costs(attacker.conditions)
    if "grappled" in costs and combat_grapple.grappler_id(attacker.conditions) == target.id:
        total = roller.randint(1, 20) + max(
            attribute_modifier(attacker.attributes.get("strength", 10)),
            attribute_modifier(attacker.attributes.get("dexterity", 10)),
        )
        dc = combat_grapple.escape_dc(target)
        escaped = total >= dc
        if escaped:
            attacker.conditions = conditions.remove_condition(attacker.conditions, "grappled")
        return {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "target": target.name,
            "escape_total": total,
            "escape_dc": dc,
            "escape": "escaped" if escaped else "failed",
        }
    if target.id == attacker.id:
        if "prone" not in costs:
            raise ValueError(f"{attacker.name} ({attacker.id}) is not prone and cannot stand")
        attacker.conditions = conditions.remove_condition(attacker.conditions, "prone")
        return {
            "actor_id": attacker.id,
            "resolved": True,
            "declaration_type": str(decl.type),
            "stood_up": True,
        }

    summary = {
        "actor_id": attacker.id,
        "resolved": True,
        "declaration_type": str(decl.type),
        "target": target.name,
    }
    if conditions.has_condition(target.conditions, "prone"):
        return {**summary, "shove": "already_prone"}

    actor_total = roller.randint(1, 20) + attribute_modifier(attacker.attributes.get("strength", 10))
    advantage_sources = {target.advantage_vs[token] for token in ("prone", "push") if token in target.advantage_vs}
    target_roll = roller.randint(1, 20)
    if advantage_sources:
        target_roll = max(target_roll, roller.randint(1, 20))
    target_total = target_roll + max(
        attribute_modifier(target.attributes.get("strength", 10)),
        attribute_modifier(target.attributes.get("dexterity", 10)),
    )
    summary.update(actor_total=actor_total, target_total=target_total)
    if advantage_sources:
        summary["advantage_vs"] = ", ".join(sorted(advantage_sources))
    if actor_total <= target_total:
        return {**summary, "shove": "resisted"}
    if not _land_condition_on_one(state, target.id, attacker, "prone", source="shove"):
        # A won contest that still lands nothing means the target is immune to prone. Name WHICH
        # immunity: a carried item (condition_immunities) or the skill capability (prone_immunity).
        blocked = {**summary, "shove": "resisted"}
        item_immunity = target.condition_immunities.get("prone")
        if item_immunity:
            blocked["condition_immunity_source"] = item_immunity
        if target.prone_immunity:
            blocked["prone_immunity"] = target.prone_immunity
        return blocked
    return {**summary, "shove": "knocked_prone"}
