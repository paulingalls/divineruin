"""Pure-function character creation rules. Zero IO, zero async.

All functions are deterministic and fully testable without external dependencies.
"""

from __future__ import annotations

from creation_data import CLASSES, DEITIES, RACES
from rules_engine import attribute_modifier

BASE_ATTRIBUTE = 10

# Culture inference mapping: (race_affinity, class_category_affinity, deity_affinity) -> cultures
# Each culture has a primary god and racial lean from the lore.
CULTURE_MAP: dict[str, dict] = {
    "sunward_accord": {
        "races": {"human", "elari", "korath", "vaelti", "thessyn", "draethar"},
        "categories": {"support", "arcane", "shadow"},
        "deities": {"aelora", "none"},
        "weight": 1,  # default fallback
    },
    "drathian_clans": {
        "races": {"human", "draethar"},
        "categories": {"martial"},
        "deities": {"kaelen"},
        "weight": 0,
    },
    "thornwardens": {
        "races": {"elari", "vaelti"},
        "categories": {"primal"},
        "deities": {"thyra"},
        "weight": 0,
    },
    "keldaran_holds": {
        "races": {"korath", "human"},
        "categories": {"martial", "arcane"},
        "deities": {"aelora", "kaelen"},
        "weight": 0,
    },
    "marsh_kindred": {
        "races": {"vaelti", "thessyn"},
        "categories": {"shadow"},
        "deities": {"syrath"},
        "weight": 0,
    },
    "dawnsworn": {
        "races": {"human", "elari", "korath", "vaelti", "thessyn", "draethar"},
        "categories": {"divine"},
        "deities": {"orenthel"},
        "weight": 0,
    },
    "tidecallers": {
        "races": {"thessyn", "human"},
        "categories": {"primal", "arcane"},
        "deities": {"nythera"},
        "weight": 0,
    },
    "aelindran_diaspora": {
        "races": {"elari", "human"},
        "categories": {"arcane"},
        "deities": {"veythar"},
        "weight": 0,
    },
}

# Starting locations per culture (all funnel to Greyvale arc for MVP)
CULTURE_START_LOCATIONS: dict[str, str] = {
    "sunward_accord": "accord_market_square",
    "drathian_clans": "accord_market_square",
    "thornwardens": "accord_market_square",
    "keldaran_holds": "accord_market_square",
    "marsh_kindred": "accord_market_square",
    "dawnsworn": "accord_market_square",
    "tidecallers": "accord_market_square",
    "aelindran_diaspora": "accord_market_square",
}

DEFAULT_START_LOCATION = "accord_market_square"


def generate_attributes(race_id: str, class_id: str) -> dict[str, int]:
    """Base 10 + race bonuses. Thessyn gets +1 to class primary attribute."""
    attrs = {
        "strength": BASE_ATTRIBUTE,
        "dexterity": BASE_ATTRIBUTE,
        "constitution": BASE_ATTRIBUTE,
        "intelligence": BASE_ATTRIBUTE,
        "wisdom": BASE_ATTRIBUTE,
        "charisma": BASE_ATTRIBUTE,
    }

    race = RACES.get(race_id)
    if race is None:
        return attrs

    # Apply race bonuses
    for attr, bonus in race.attribute_bonuses.items():
        if attr in attrs:
            attrs[attr] += bonus

    # Thessyn adaptive bonus: +1 to class primary attribute
    if race_id == "thessyn":
        cls = CLASSES.get(class_id)
        if cls and cls.primary_attribute in attrs:
            attrs[cls.primary_attribute] += 1

    return attrs


def calculate_starting_hp(class_id: str, constitution: int) -> dict[str, int]:
    """Max hit die + CON modifier. Returns {current, max}."""
    cls = CLASSES.get(class_id)
    if cls is None:
        return {"current": 10, "max": 10}

    con_mod = attribute_modifier(constitution)
    hp = cls.hit_die + con_mod
    hp = max(1, hp)  # minimum 1 HP
    return {"current": hp, "max": hp}


def calculate_ac(equipment: dict, dexterity: int) -> int:
    """AC from armor ac_bonus + DEX modifier (capped by armor type) + shield."""
    dex_mod = attribute_modifier(dexterity)

    armor = equipment.get("armor")
    if armor is None:
        base_ac = 10 + dex_mod
    else:
        base_ac = armor.get("ac_bonus", 10)
        # Heavy armor (base_ac >= 15): no DEX bonus
        # Medium armor (base_ac >= 12): DEX capped at +2
        # Light armor (base_ac < 12): full DEX
        if base_ac >= 15:
            pass  # no dex bonus
        elif base_ac >= 12:
            base_ac += min(dex_mod, 2)
        else:
            base_ac += dex_mod

    shield = equipment.get("shield")
    if shield is not None:
        base_ac += shield.get("ac_bonus", 0)

    return base_ac


def get_starting_equipment(class_id: str) -> dict:
    """Returns {main_hand, armor, shield} matching player data shape."""
    cls = CLASSES.get(class_id)
    if cls is None:
        return {"main_hand": None, "armor": None, "shield": None}
    return dict(cls.starting_equipment)


def get_skill_proficiencies(class_id: str, skill_choices: list[str] | None = None) -> list[str]:
    """Return skill proficiencies for a class.

    If skill_choices is provided and valid, use those. Otherwise, default to
    the first N from skill_options.
    """
    cls = CLASSES.get(class_id)
    if cls is None:
        return []

    if skill_choices:
        # Validate choices are from the class pool and correct count
        valid = [s for s in skill_choices if s in cls.skill_options]
        if len(valid) == cls.num_skill_choices:
            return valid

    # Default: first N from skill_options
    return list(cls.skill_options[: cls.num_skill_choices])


def infer_culture(race_id: str, class_id: str, deity_id: str | None) -> list[str]:
    """Return 1-3 culture IDs ranked by narrative fit.

    Scoring: +3 race match, +2 category match, +2 deity match, +weight.
    """
    cls = CLASSES.get(class_id)
    category = cls.category if cls else ""
    deity = deity_id or "none"

    scored: list[tuple[int, str]] = []
    for culture_id, info in CULTURE_MAP.items():
        score = info.get("weight", 0)
        if race_id in info["races"]:
            score += 3
        if category in info["categories"]:
            score += 2
        if deity in info["deities"]:
            score += 2
        scored.append((score, culture_id))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Return top 1-3 based on score spread
    results = [scored[0][1]]
    top_score = scored[0][0]
    for score, cid in scored[1:3]:
        if score >= top_score - 2:
            results.append(cid)
    return results


def get_starting_location(culture_id: str) -> str:
    """Map culture -> safe starting location_id."""
    return CULTURE_START_LOCATIONS.get(culture_id, DEFAULT_START_LOCATION)


def build_character_data(
    name: str,
    race_id: str,
    class_id: str,
    deity_id: str | None,
    backstory: str,
    skill_choices: list[str] | None = None,
) -> dict:
    """Compose all creation rules into the complete player data JSONB dict.

    Output shape matches content/players.json + race/deity fields.
    """
    cls = CLASSES.get(class_id)
    if cls is None:
        raise ValueError(f"Unknown class: {class_id}")
    if race_id not in RACES:
        raise ValueError(f"Unknown race: {race_id}")
    if deity_id is not None and deity_id != "none" and deity_id not in DEITIES:
        raise ValueError(f"Unknown deity: {deity_id}")

    attributes = generate_attributes(race_id, class_id)
    hp = calculate_starting_hp(class_id, attributes["constitution"])
    equipment = get_starting_equipment(class_id)
    ac = calculate_ac(equipment, attributes["dexterity"])
    proficiencies = get_skill_proficiencies(class_id, skill_choices)

    cultures = infer_culture(race_id, class_id, deity_id)
    location_id = get_starting_location(cultures[0])

    return {
        "name": name,
        "race": race_id,
        "class": class_id,
        "level": 1,
        "xp": 0,
        "location_id": location_id,
        "attributes": attributes,
        "hp": hp,
        "ac": ac,
        "proficiencies": proficiencies,
        "saving_throw_proficiencies": list(cls.saving_throw_proficiencies),
        "equipment": equipment,
        "inventory": [],
        "gold": cls.starting_gold,
        "backstory": backstory,
        "deity": deity_id,
        "culture": cultures[0],
        "divine_favor": {
            "patron": deity_id or "none",
            "level": 0,
            "max": 100,
            "last_whisper_level": 0,
        },
    }
