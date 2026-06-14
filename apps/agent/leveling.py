"""Level progression table and level-up reward aggregation. Zero IO, zero async."""

from dataclasses import dataclass
from typing import Literal

from hp_scaling import calculate_max_hp
from rules_engine import proficiency_bonus

# --- Type aliases ---

MilestoneType = Literal[
    "elective_techniques",
    "specialization",
    "specialization_ability",
    "passive_upgrade",
    "proficiency_increase",
    "archetype_milestone",
    "archetype_capstone",
]


# --- Spell tier unlock gate (per-archetype, M3.2 story-008) ---

# The five spell tiers, low->high — the closed vocabulary the gate validates against.
SPELL_TIERS: frozenset[str] = frozenset({"cantrip", "minor", "standard", "major", "supreme"})

# Minimum character level for each archetype to learn/prepare an elective spell of each
# tier, sourced from game_mechanics_archetypes.md "Max Tier by level" tables. A tier
# ABSENT from an archetype's map is never available to it (paladin/diplomat/marshal have
# no Supreme; the half-casters and Whisper have no elective cantrip). An archetype absent
# from the table is a non-caster (fail loud). The old single global table (standard 4 /
# major 7 / supreme 13) matched only Whisper — full casters unlock at 3 / 5 / 9, the
# divergence concern 66fa8bae flagged.
_FULL_CASTER: dict[str, int] = {"cantrip": 1, "minor": 1, "standard": 3, "major": 5, "supreme": 9}
MIN_LEVEL_BY_ARCHETYPE_TIER: dict[str, dict[str, int]] = {
    "mage": _FULL_CASTER,
    "artificer": _FULL_CASTER,
    "seeker": _FULL_CASTER,
    "druid": _FULL_CASTER,
    "beastcaller": _FULL_CASTER,
    "warden": _FULL_CASTER,
    "cleric": _FULL_CASTER,
    "oracle": _FULL_CASTER,
    # Bard Supreme unlocks at L10, not L9 — the lone full-caster outlier (Mass Inspire is
    # core at L9, Supreme arrives at L10). Ref: game_mechanics_archetypes.md:399-400.
    "bard": {"cantrip": 1, "minor": 1, "standard": 3, "major": 5, "supreme": 10},
    # Half-casters: elective spells start at L3, cap at Major, no Supreme (spec
    # archetypes.md:807-811 paladin / 1057-1060 diplomat / 1132-1135 marshal).
    "paladin": {"minor": 3, "standard": 5, "major": 9},
    "diplomat": {"minor": 3, "standard": 5, "major": 9},
    "marshal": {"minor": 3, "standard": 5, "major": 9},
    # Whisper's shadow-magic catalog: the lone caster matching the old global 4/7/13
    # (spec archetypes.md:983-986).
    "whisper": {"minor": 1, "standard": 4, "major": 7, "supreme": 13},
}


def min_level_for_tier(archetype: str, tier: str) -> int | None:
    """Minimum character level for `archetype` to access spell `tier`, or None when the
    tier is never available to that archetype (e.g. paladin Supreme).

    Fails loud on an unknown tier or a non-caster archetype — callers must pass a known
    spell_tier (cantrip/minor/standard/major/supreme) and a spellcasting archetype.
    """
    if tier not in SPELL_TIERS:
        raise ValueError(f"unknown spell tier {tier!r}; expected one of {sorted(SPELL_TIERS)}")
    if archetype not in MIN_LEVEL_BY_ARCHETYPE_TIER:
        raise ValueError(
            f"unknown spellcasting archetype {archetype!r}; expected one of {sorted(MIN_LEVEL_BY_ARCHETYPE_TIER)}"
        )
    return MIN_LEVEL_BY_ARCHETYPE_TIER[archetype].get(tier)


def is_spell_tier_unlocked(archetype: str, tier: str, level: int) -> bool:
    """True if a character of `archetype` at `level` may learn/prepare a `tier` spell.

    Fails loud on an unknown tier or a non-caster archetype (see min_level_for_tier).
    """
    floor = min_level_for_tier(archetype, tier)
    return floor is not None and level >= floor


# --- Cantrip damage scaling (M3.3) ---


# Character-level brackets to cantrip damage dice. The numeric SSOT cast_spell
# (story-004) consumes; the LEVEL_PROGRESSION narration strings ("scales to 3d6")
# stay for DM flavor. Ref: 03_magic.md L132, game_mechanics_combat.md L235.
def cantrip_damage_dice(level: int) -> str:
    """Cantrip damage dice notation (NdM) for a character of `level`.

    Brackets: 1d6 (L1-4), 2d6 (L5-10), 3d6 (L11-16), 4d6 (L17-20). The returned
    spec is valid `dice.roll` notation. Fails loud (ValueError) outside L1-20 —
    callers must pass a valid character level, never default it.
    """
    if not 1 <= level <= 20:
        raise ValueError(f"level {level} out of range; expected a character level 1-20")
    if level <= 4:
        return "1d6"
    if level <= 10:
        return "2d6"
    if level <= 16:
        return "3d6"
    return "4d6"


# --- Data structures ---


@dataclass(frozen=True)
class LevelProgression:
    level: int
    proficiency_bonus: int
    attribute_points: int  # 0 or 2
    specialization_fork: bool
    milestone_type: MilestoneType | None
    milestone_description: str | None
    notable: str | None


@dataclass(frozen=True)
class LevelUpRewards:
    from_level: int
    to_level: int
    attribute_points: int
    specialization_fork: bool
    proficiency_changed: bool
    new_proficiency_bonus: int
    milestones: list[dict]


# --- Progression table (sourced from game_mechanics_core.md L628-660) ---

LEVEL_PROGRESSION: dict[int, LevelProgression] = {
    1: LevelProgression(
        1,
        proficiency_bonus(1),
        0,
        False,
        None,
        None,
        "Character creation. Core spells/abilities known",
    ),
    2: LevelProgression(
        2,
        proficiency_bonus(2),
        0,
        False,
        None,
        None,
        "First training cycles available",
    ),
    3: LevelProgression(
        3,
        proficiency_bonus(3),
        0,
        False,
        "passive_upgrade",
        "New passive or ability upgrade. Companion gains new passive",
        "Companion gains new passive",
    ),
    4: LevelProgression(
        4,
        proficiency_bonus(4),
        2,
        False,
        "elective_techniques",
        "L4 Elective techniques — martials choose from pool of 4. Standard spells unlock",
        "First martial elective choice",
    ),
    5: LevelProgression(
        5,
        proficiency_bonus(5),
        0,
        True,
        "specialization",
        "SPECIALIZATION — choose 1 of 2 paths. Major power spike. Identity-defining fork",
        "Major power spike. Identity-defining fork",
    ),
    6: LevelProgression(
        6,
        proficiency_bonus(6),
        0,
        False,
        "specialization_ability",
        "Specialization ability unlocked",
        None,
    ),
    7: LevelProgression(
        7,
        proficiency_bonus(7),
        0,
        False,
        "proficiency_increase",
        "Proficiency bonus increases to +2. Major spells unlock",
        "Proficiency increase",
    ),
    8: LevelProgression(
        8,
        proficiency_bonus(8),
        2,
        False,
        "elective_techniques",
        "L8 Elective techniques — martials choose from pool of 4",
        "Second martial elective choice",
    ),
    9: LevelProgression(
        9,
        proficiency_bonus(9),
        0,
        False,
        "passive_upgrade",
        "New passive or ability upgrade",
        None,
    ),
    10: LevelProgression(
        10,
        proficiency_bonus(10),
        0,
        False,
        "archetype_milestone",
        "ARCHETYPE MILESTONE — major new ability. Extra Attack for Warrior, Skirmisher, Paladin. Companion major upgrade",
        "Companion major upgrade",
    ),
    11: LevelProgression(
        11,
        proficiency_bonus(11),
        0,
        False,
        "specialization_ability",
        "Specialization ability. Cantrip damage scales to 3d6",
        "Cantrip damage scales to 3d6",
    ),
    12: LevelProgression(
        12,
        proficiency_bonus(12),
        2,
        False,
        None,
        None,
        None,
    ),
    13: LevelProgression(
        13,
        proficiency_bonus(13),
        0,
        False,
        "passive_upgrade",
        "New passive or ability upgrade. Supreme spells unlock",
        None,
    ),
    14: LevelProgression(
        14,
        proficiency_bonus(14),
        0,
        False,
        "proficiency_increase",
        "Proficiency bonus increases to +3",
        "Proficiency increase",
    ),
    15: LevelProgression(
        15,
        proficiency_bonus(15),
        0,
        False,
        "archetype_milestone",
        "ARCHETYPE MILESTONE — capstone ability preview. Companion capstone ability",
        "Companion capstone ability",
    ),
    16: LevelProgression(
        16,
        proficiency_bonus(16),
        2,
        False,
        None,
        None,
        None,
    ),
    17: LevelProgression(
        17,
        proficiency_bonus(17),
        0,
        False,
        "specialization_ability",
        "Specialization ability. Cantrip damage scales to 4d6",
        "Cantrip damage scales to 4d6",
    ),
    18: LevelProgression(
        18,
        proficiency_bonus(18),
        0,
        False,
        None,
        None,
        None,
    ),
    19: LevelProgression(
        19,
        proficiency_bonus(19),
        0,
        False,
        None,
        None,
        None,
    ),
    20: LevelProgression(
        20,
        proficiency_bonus(20),
        2,
        False,
        "archetype_capstone",
        "ARCHETYPE CAPSTONE — defining ultimate ability. Companion legendary. Total attribute points: +10 from levels",
        "Companion legendary",
    ),
}

# --- Milestone narration templates ---

_MILESTONE_NARRATIONS: dict[int, str] = {
    3: "A new power stirs within you — a passive ability sharpens, and your companion senses the change.",
    4: "New combat techniques reveal themselves. Choose your elective wisely — this shapes how you fight.",
    5: (
        "You stand at the crossroads of your path. Two specializations diverge before you — "
        "this fork defines who you will become. Choose the path that calls to your soul."
    ),
    6: "Your chosen specialization deepens. A new ability crystallizes from your training.",
    7: "Your proficiency grows. The world bends a little more to your will. Major magic awaits.",
    8: "Advanced techniques emerge from your experience. A second elective choice stands before you.",
    9: "Another passive power awakens, honed by countless battles and trials.",
    10: (
        "A milestone of power — your archetype reveals its true nature. "
        "Warriors find their blade striking twice, casters unlock devastating abilities. "
        "Your companion undergoes a major transformation."
    ),
    11: "Your specialization ability evolves further. Cantrips surge with triple the force.",
    13: "A new passive emerges as supreme-tier magic becomes available to those who wield it.",
    14: "Your proficiency reaches its peak tier. Few in Aethos can match your expertise.",
    15: (
        "An archetype milestone of mastery — a preview of your capstone power. "
        "Your companion gains its capstone ability. You are among the most powerful in Aethos."
    ),
    17: "Your specialization ability reaches its final form. Cantrip damage scales to devastating heights.",
    20: (
        "You have reached the ultimate pinnacle — your archetype capstone ability defines your legend. "
        "Your companion ascends to legendary status. You are a force of nature."
    ),
}


# --- Public API ---


def get_level_up_rewards(from_level: int, to_level: int) -> LevelUpRewards:
    """Aggregate rewards for leveling from from_level to to_level (exclusive of from_level)."""
    if to_level <= from_level:
        return LevelUpRewards(
            from_level=from_level,
            to_level=to_level,
            attribute_points=0,
            specialization_fork=False,
            proficiency_changed=False,
            new_proficiency_bonus=proficiency_bonus(from_level),
            milestones=[],
        )

    total_attr = 0
    spec_fork = False
    milestones: list[dict] = []

    for lvl in range(from_level + 1, to_level + 1):
        entry = LEVEL_PROGRESSION[lvl]
        total_attr += entry.attribute_points
        if entry.specialization_fork:
            spec_fork = True
        if entry.milestone_type is not None and entry.milestone_description is not None:
            milestones.append(
                {
                    "level": lvl,
                    "type": entry.milestone_type,
                    "description": entry.milestone_description,
                }
            )

    old_prof = proficiency_bonus(from_level)
    new_prof = proficiency_bonus(to_level)

    return LevelUpRewards(
        from_level=from_level,
        to_level=to_level,
        attribute_points=total_attr,
        specialization_fork=spec_fork,
        proficiency_changed=old_prof != new_prof,
        new_proficiency_bonus=new_prof,
        milestones=milestones,
    )


def build_level_up_payload(from_level: int, rewards: LevelUpRewards) -> dict:
    """Build the LEVEL_UP event payload dict from rewards."""
    return {
        "from_level": from_level,
        "to_level": rewards.to_level,
        "attribute_points": rewards.attribute_points,
        "specialization_fork": rewards.specialization_fork,
        "proficiency_changed": rewards.proficiency_changed,
        "new_proficiency_bonus": rewards.new_proficiency_bonus,
        "milestones": rewards.milestones,
    }


def get_milestone_narration(level: int) -> str | None:
    """Get a narration template for a milestone level, or None if no milestone."""
    return _MILESTONE_NARRATIONS.get(level)


def build_level_up_payload_for_archetype(
    from_level: int,
    rewards: LevelUpRewards,
    archetype: str,
    con_mod: int = 0,
) -> dict:
    """Level-up payload + per-level hp_gains deltas from calculate_max_hp(archetype, level, con_mod). Ref: game_mechanics_core.md L632."""
    payload = build_level_up_payload(from_level, rewards)
    hp_gains = [
        {
            "level": lvl,
            "hp_gain": calculate_max_hp(archetype, lvl, con_mod) - calculate_max_hp(archetype, lvl - 1, con_mod),
        }
        for lvl in range(from_level + 1, rewards.to_level + 1)
    ]
    return {**payload, "hp_gains": hp_gains}
