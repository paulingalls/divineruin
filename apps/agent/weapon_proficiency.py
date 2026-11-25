"""Catalog weapon profiles and archetype proficiency rules."""

from collections.abc import Sequence

CATEGORIES = ("simple", "martial")
RANGES = ("melee", "ranged")
KINDS = (
    "battleaxe",
    "club",
    "dagger",
    "garrote",
    "greataxe",
    "greatsword",
    "halberd",
    "handaxe",
    "hand_crossbow",
    "heavy_crossbow",
    "light_crossbow",
    "longbow",
    "longsword",
    "lute",
    "mace",
    "quarterstaff",
    "rapier",
    "scimitar",
    "shortbow",
    "shortsword",
    "sling",
    "spear",
    "tools",
    "warhammer",
)
PROFILE_FIELDS = {"weapon_category": CATEGORIES, "weapon_range": RANGES, "weapon_kind": KINDS}
CATEGORY_RANGES = {f"{category}_{distance}": (category, distance) for category in CATEGORIES for distance in RANGES}
GROUP_KINDS = {"martial_polearms": "halberd", "martial_hammers": "warhammer"}
PROFICIENCIES = (*CATEGORIES, *KINDS, *CATEGORY_RANGES, *GROUP_KINDS, "light_weapons", "staff")


def validate_weapon_profile(item_id: str, data: dict) -> dict[str, str] | None:
    if data.get("type") != "weapon":
        return None
    profile = {}
    for field, allowed in PROFILE_FIELDS.items():
        value = data.get(field)
        if value not in allowed:
            raise ValueError(f"item {item_id!r} {field} {value!r} is invalid")
        profile[field] = value
    return profile


def parse_weapon_proficiencies(archetype_id: str, raw: object) -> tuple[str, ...]:
    context = f"archetype {archetype_id!r} weapon_proficiencies"
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{context} must be a nonempty list")
    for token in raw:
        if token not in PROFICIENCIES:
            raise ValueError(f"{context} contains invalid token {token!r}")
    return tuple(raw)


def _covers(token: str, weapon: dict) -> bool:
    category = weapon["weapon_category"]
    if token in CATEGORIES:
        return token == category
    if token in CATEGORY_RANGES:
        wanted_category, wanted_range = CATEGORY_RANGES[token]
        return category == wanted_category and weapon["weapon_range"] == wanted_range
    if token in GROUP_KINDS:
        return category == "martial" and weapon["weapon_kind"] == GROUP_KINDS[token]
    if token == "light_weapons":
        return "light" in weapon.get("properties", ())
    return weapon["weapon_kind"] == ("quarterstaff" if token == "staff" else token)


def has_weapon_proficiency(proficiencies: Sequence[str], weapon: dict) -> bool:
    return any(_covers(token, weapon) for token in proficiencies)
