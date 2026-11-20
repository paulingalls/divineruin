"""Creature damage traits, validated at the catalog boundary and applied at HP landing."""

from dataclasses import replace

from condition_catalog import INCORPOREAL
from conditions import damage_hp_floor, has_condition

PHYSICAL_DAMAGE_TYPES = ("slashing", "piercing", "bludgeoning")

DAMAGE_TYPES = (
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "force",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
)
AFFINITIES = ("resistant", "immune", "vulnerable")


def validate_traits(row):
    problems = []
    if "resist_nonmagical_physical" in row and type(row["resist_nonmagical_physical"]) is not bool:
        problems.append("resist_nonmagical_physical: expected boolean")
    if "unholy_fortitude" in row:
        spec = row["unholy_fortitude"]
        if not isinstance(spec, dict):
            problems.append("unholy_fortitude: expected object")
        else:
            fields = {"save", "dc", "increment", "narration_cue"}
            for key in set(spec) - fields:
                problems.append(f"unholy_fortitude.{key}: unknown")
            for key in fields:
                value = spec.get(key)
                valid = (
                    value in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
                    if key == "save"
                    else isinstance(value, str) and bool(value.strip())
                    if key == "narration_cue"
                    else type(value) is int and value > 0
                )
                if not valid:
                    problems.append(f"unholy_fortitude.{key}: invalid")
    if "damage_affinities" in row:
        traits = row["damage_affinities"]
        if not isinstance(traits, dict):
            problems.append("damage_affinities: expected object")
        else:
            seen = set()
            for key in traits:
                if key not in AFFINITIES:
                    problems.append(f"damage_affinities.{key}: unknown affinity")
            for key in AFFINITIES:
                path = f"damage_affinities.{key}"
                if key not in traits:
                    problems.append(f"{path}: required")
                    continue
                values = traits[key]
                if not isinstance(values, list):
                    problems.append(f"{path}: expected array")
                    continue
                local = set()
                for i, value in enumerate(values):
                    if not isinstance(value, str) or value not in DAMAGE_TYPES:
                        problems.append(f"{path}[{i}]: expected damage type")
                    elif value in local:
                        problems.append(f"{path}: duplicate damage type")
                    elif value in seen:
                        problems.append(f"damage_affinities: contradictory damage type {value}")
                    else:
                        local.add(value)
                seen.update(local)
    if "tags" in row:
        tags = row["tags"]
        if not isinstance(tags, list):
            problems.append("tags: expected array")
        else:
            for i, tag in enumerate(tags):
                if tag != "plant":
                    problems.append(f"tags[{i}]: expected plant")
                elif tags[:i].count(tag):
                    problems.append("tags: duplicate tag")
    return problems


def amount(traits, damage, damage_type):
    if damage_type in traits.get("immune", []):
        return 0
    if damage_type in traits.get("resistant", []):
        return damage // 2
    if damage_type in traits.get("vulnerable", []):
        return damage * 2
    return damage


def apply(target, action, result, *, state=None):
    from still_encounter import owner_alias

    traits = target.damage_affinities
    incorporeal = has_condition(target.conditions, INCORPOREAL)
    divine_vulnerable = action.get("spell_source") == "divine" and owner_alias(state, target.id) != target.id

    def adjusted(damage, dtype, ignores_resistance=False):
        conditional = (
            target.resist_nonmagical_physical and not action.get("magical", False) and dtype in PHYSICAL_DAMAGE_TYPES
        )
        if (incorporeal and dtype in PHYSICAL_DAMAGE_TYPES) or dtype in traits.get("immune", []):
            return 0
        if not ignores_resistance and (conditional or dtype in traits.get("resistant", [])):
            return damage // 2
        if dtype in traits.get("vulnerable", []) or divine_vulnerable:
            return damage * 2
        return damage

    bonus = getattr(result, "bonus_damage", 0)
    rider = getattr(result, "rider_damage", 0)
    synergy = getattr(result, "synergy_damage", 0)
    adjusted_synergy = adjusted(synergy, getattr(result, "synergy_damage_type", None))
    adjusted_bonus = adjusted(bonus, getattr(result, "bonus_damage_type", None))
    adjusted_rider = adjusted(
        rider, getattr(result, "rider_damage_type", None), getattr(result, "rider_ignores_resistance", False)
    )
    components = action.get("damage_components")
    if components is not None:
        components = [{**c, "damage": adjusted(c["damage"], c["damage_type"])} for c in components]
        action = {**action, "damage_components": components}
        damage = sum(c["damage"] for c in components)
    else:
        damage = adjusted(result.damage - bonus - rider - synergy, result.damage_type)
    # Resistance can remove a rider that offset a negative attribute modifier.
    changes = {"damage": max(0, damage + adjusted_bonus + adjusted_rider + adjusted_synergy)}
    if hasattr(result, "bonus_damage"):
        changes.update(bonus_damage=adjusted_bonus, rider_damage=adjusted_rider, synergy_damage=adjusted_synergy)
    if hasattr(result, "target_hp_remaining") and changes["damage"] != result.damage:
        return action, with_landed_damage(
            result, changes.pop("damage"), target.hp_current, hp_floor=damage_hp_floor(target.conditions), **changes
        )
    return action, replace(result, **changes)


def with_landed_damage(result, damage, hp_before, *, hp_floor=0, **changes):
    """Rewrite a hit's damage after the roll and keep its kill verdict true to the HP it lands.

    A post-roll rewrite (a reaction's halving, a target's resistance or vulnerability) can save a
    target the raw roll killed, or kill one it spared; the DM must never hear a killing blow on a
    creature still standing, nor miss one that falls.
    """
    remaining = max(hp_floor, hp_before - damage)
    killed = result.hit and remaining == 0
    fields = {
        "damage": damage,
        "target_hp_remaining": remaining,
        "overkill": max(0, damage - hp_before) if killed else 0,
        "target_killed": killed,
        **changes,
    }
    if killed and result.context not in ("natural_20", "critical_hit"):
        fields["dramatic"], fields["context"] = True, "killing_blow"
    elif result.context == "killing_blow":
        fields["dramatic"], fields["context"] = False, ""
    return replace(result, **fields)
