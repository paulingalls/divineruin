"""Creature damage traits, validated at the catalog boundary and applied at HP landing."""

from dataclasses import replace

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


def apply(target, action, result):
    traits = target.damage_affinities
    bonus = getattr(result, "bonus_damage", 0)
    adjusted_bonus = amount(traits, bonus, getattr(result, "bonus_damage_type", None))
    components = action.get("damage_components")
    if components is not None:
        components = [{**c, "damage": amount(traits, c["damage"], c["damage_type"])} for c in components]
        action = {**action, "damage_components": components}
        damage = sum(c["damage"] for c in components)
    else:
        damage = amount(traits, result.damage - bonus, result.damage_type)
    changes = {"damage": damage + adjusted_bonus}
    if hasattr(result, "bonus_damage"):
        changes["bonus_damage"] = adjusted_bonus
    return action, replace(result, **changes)
