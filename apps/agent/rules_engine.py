"""Core rules engine — character math, resource pools, leveling. Zero IO, zero async."""

from dataclasses import dataclass
from typing import Literal

# --- Type aliases ---

SkillTier = Literal["untrained", "trained", "expert", "master"]
DcTier = Literal["trivial", "easy", "moderate", "hard", "very_hard", "extreme", "legendary"]
ResourcePattern = Literal["stamina_only", "focus_only", "focus_primary", "split"]


# --- Resource pool config ---


@dataclass(frozen=True)
class PoolFormula:
    base: int  # 4, 5, 6, or 8
    attribute: str  # "strength", "constitution", etc.
    level_divisor: int  # 1=+level, 2=+level//2, 3=+level//3, 0=flat


@dataclass(frozen=True)
class PoolMaximums:
    stamina: int | None  # None = archetype has no pool
    focus: int | None
    pattern: ResourcePattern


ARCHETYPE_RESOURCE_CONFIG: dict[str, tuple[ResourcePattern, PoolFormula | None, PoolFormula | None]] = {
    # Stamina-only
    "warrior": ("stamina_only", PoolFormula(8, "constitution", 1), None),
    "guardian": ("stamina_only", PoolFormula(8, "constitution", 1), None),
    "skirmisher": ("stamina_only", PoolFormula(8, "dexterity", 1), None),
    "rogue": ("stamina_only", PoolFormula(8, "dexterity", 1), None),
    "spy": ("stamina_only", PoolFormula(8, "charisma", 1), None),
    # Focus-only
    "mage": ("focus_only", None, PoolFormula(8, "intelligence", 1)),
    "artificer": ("focus_only", None, PoolFormula(8, "intelligence", 1)),
    "seeker": ("focus_only", None, PoolFormula(8, "intelligence", 1)),
    "whisper": ("focus_only", None, PoolFormula(6, "intelligence", 2)),
    # Focus-primary
    "druid": ("focus_primary", PoolFormula(4, "constitution", 0), PoolFormula(8, "wisdom", 1)),
    "cleric": ("focus_primary", PoolFormula(4, "constitution", 0), PoolFormula(8, "wisdom", 1)),
    "beastcaller": ("focus_primary", PoolFormula(4, "constitution", 0), PoolFormula(8, "wisdom", 1)),
    "warden": ("focus_primary", PoolFormula(6, "constitution", 0), PoolFormula(8, "wisdom", 1)),
    "paladin": ("focus_primary", PoolFormula(6, "constitution", 3), PoolFormula(6, "wisdom", 1)),
    "oracle": ("focus_primary", PoolFormula(4, "constitution", 0), PoolFormula(8, "wisdom", 1)),
    # Split
    "bard": ("split", PoolFormula(5, "constitution", 2), PoolFormula(5, "charisma", 2)),
    "diplomat": ("split", PoolFormula(5, "charisma", 2), PoolFormula(5, "charisma", 2)),
    "marshal": ("split", PoolFormula(6, "strength", 2), PoolFormula(5, "charisma", 2)),
}


def _apply_pool_formula(formula: PoolFormula, level: int, attribute_modifiers: dict[str, int]) -> int:
    """Calculate a single pool maximum from its formula."""
    attr_mod = attribute_modifiers.get(formula.attribute, 0)
    if formula.level_divisor == 0:
        return formula.base + attr_mod
    return formula.base + attr_mod + level // formula.level_divisor


def calculate_max_pools(
    archetype: str,
    level: int,
    attribute_modifiers: dict[str, int],
) -> PoolMaximums:
    """Calculate Stamina and Focus pool maximums for an archetype at a given level.

    Args:
        archetype: Archetype id (lowercase, e.g. "warrior").
        level: Character level (1-20).
        attribute_modifiers: Dict of attribute name to pre-computed modifier.
    """
    if archetype not in ARCHETYPE_RESOURCE_CONFIG:
        raise ValueError(f"Unknown archetype: {archetype!r}")

    pattern, stamina_formula, focus_formula = ARCHETYPE_RESOURCE_CONFIG[archetype]

    stamina = _apply_pool_formula(stamina_formula, level, attribute_modifiers) if stamina_formula else None
    focus = _apply_pool_formula(focus_formula, level, attribute_modifiers) if focus_formula else None

    return PoolMaximums(stamina=stamina, focus=focus, pattern=pattern)


# --- Constants ---

SKILLS: dict[str, str | tuple[str, ...]] = {
    # Physical
    "athletics": "strength",
    "acrobatics": "dexterity",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "endurance": "constitution",
    # Mental
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    "crafting": ("intelligence", "wisdom"),
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    "insight": "wisdom",
    "animal_handling": "wisdom",
    # Social
    "persuasion": "charisma",
    "deception": "charisma",
    "intimidation": "charisma",
    "performance": "charisma",
}

DC_TIERS: dict[str, int] = {
    "trivial": 5,
    "easy": 8,
    "moderate": 12,
    "hard": 16,
    "very_hard": 20,
    "extreme": 24,
    "legendary": 28,
    "deadly": 24,  # deprecated alias → extreme
}

SKILL_TIER_BONUS: dict[str, int] = {
    "untrained": 0,
    "trained": 2,
    "expert": 4,
    "master": 5,
}

SKILL_TIER_ORDER: list[str] = ["untrained", "trained", "expert", "master"]


def proficiency_bonus(level: int) -> int:
    """Bounded proficiency scale: +1 (L1-6), +2 (L7-13), +3 (L14-20)."""
    if level <= 6:
        return 1
    if level <= 13:
        return 2
    return 3


PROFICIENCY_BY_LEVEL: dict[int, int] = {lvl: proficiency_bonus(lvl) for lvl in range(1, 21)}

ADVANCEMENT_THRESHOLDS: dict[str, int] = {
    "untrained": 8,
    "trained": 20,
    "expert": 40,
}

SKILL_CAPABILITIES: dict[str, dict[str, str]] = {
    "athletics": {
        "expert": "Attempt superhuman feats: break reinforced doors, leap gaps wider than 10 ft, grapple creatures one size larger.",
        "master": "Immovable Anchor — Cannot be forcibly moved against your will (shoved, pushed, thrown, pulled by spells) unless you choose to allow it. Cannot fall prone from physical force.",
    },
    "acrobatics": {
        "expert": "Attempt impossible movement: run along walls briefly, flip over enemies to reposition, land from any fall under 40 ft without damage.",
        "master": "Perfect Balance — Cannot be knocked prone. Cannot trigger pressure plates, tripwires, or step-activated traps. Can stand on any surface regardless of width or angle.",
    },
    "stealth": {
        "expert": "Hide in plain sight: attempt to become hidden even when actively observed, as long as any visual obstruction exists (dim light, light cover, crowd).",
        "master": "Ghost Walk — While hidden, movement makes no sound at all. Cannot be detected by hearing, tremorsense, or non-visual senses. Only direct line of sight or magical detection reveals you.",
    },
    "sleight_of_hand": {
        "expert": "Attempt during combat: plant items on enemies, steal worn objects, swap held items with decoys. Pick locks under time pressure without disadvantage.",
        "master": "Impossible Hands — Pick any non-magical lock automatically (no roll, just time). Palm or swap objects a creature is actively gripping (contested check only vs Expert+ Perception).",
    },
    "endurance": {
        "expert": "Forced march 24 hours without exhaustion. Hold breath 10 minutes. Resist first stage of progressive conditions (poison, disease, Hollowed) automatically for 1 hour.",
        "master": "Iron Constitution — Exhaustion caps at 3 stacks (others cap at 5). Immune to non-magical disease. Short rests take 30 minutes instead of 1 hour.",
    },
    "arcana": {
        "expert": "Identify any spell being cast in real time (no check). Sense approximate Resonance levels of nearby casters and local Veil condition. Detect magical traps, wards, and enchantments by sight.",
        "master": "Arcane Intuition — Instinctively know Focus cost and Resonance generation of any spell before casting, including environmental modifiers. Sense exact magical properties of any touched item (no Detect Magic needed). DM reveals all magical information automatically.",
    },
    "history": {
        "expert": "DM volunteers relevant historical context during exploration and NPC interactions without you asking. Identify cultural origin, age, and significance of artifacts and ruins.",
        "master": "Living Archive — Once per session, declare 'I remember reading about this.' DM must provide one useful, true, relevant fact about the current situation, NPC, or location from world history.",
    },
    "investigation": {
        "expert": "Reconstruct events from evidence: at crime scenes, ambush sites, or abandoned camps, the DM narrates what happened, who was involved, and when. See through disguises and illusions with a check.",
        "master": "Deductive Engine — When entering a new room, area, or scene, the DM automatically reveals the single most important hidden detail (concealed door, trap, hidden NPC, most valuable item). No search action required.",
    },
    "nature": {
        "expert": "Identify any natural creature's strengths and weaknesses on sight (DM reveals resistances, vulnerabilities, behavior). Predict weather 24 hours ahead with certainty. Identify all plants and fungi including rare alchemical ingredients.",
        "master": "Naturalist's Sense — Sense the health and mood of every living thing within earshot. Animals do not attack you unless magically compelled. DM tells you when the local ecosystem is abnormal, including subtle Hollow corruption not yet visibly manifested.",
    },
    "religion": {
        "expert": "Identify divine magic on sight (which god, what purpose). Sense consecrated and desecrated ground without check. Recognize followers of any god by behavioral patterns.",
        "master": "Theologian's Insight — Understand the mechanical relationship between gods and the Veil theoretically. DM shares additional lore during divine encounters. Once per session, predict how a god-agent will respond to a player action before it happens.",
    },
    "crafting": {
        "expert": "Veil-Stabilized Crafting — Imbue items with magical properties during async crafting using rare materials. Create items with Resonance interactions. Work safely with Hollow-touched materials that would corrupt untrained hands.",
        "master": "Masterwork Creation — Once per completed crafting project, declare the item a Masterwork. Define a unique property in collaboration with the DM, themed to materials and method. Masterwork items are named, tracked, and can become legendary gear.",
    },
    "medicine": {
        "expert": "Stabilize dying creatures automatically (no check). Diagnose any non-magical condition by observation. Short rest medical attention restores 1d6 extra HP to one patient. Identify poisons and antidotes on sight.",
        "master": "Field Surgeon — During short rest, remove one negative condition (Poisoned, Wounded, Blinded, stage 1 Hollowed) from a patient with no Focus cost. Automatically detect when a creature is under magical compulsion (Charmed, Dominated) by observing behavior.",
    },
    "perception": {
        "expert": "Passive detection radius doubled. DM tells you when someone is watching you (even if unidentified). Process background sounds for useful information (overhear distant conversations, estimate enemy numbers from footsteps).",
        "master": "Omniscient Awareness — Cannot be surprised, ever. Always aware of every creature within earshot, including hidden ones. DM shares ambient information automatically: nearby creature count, environmental state, changes since last visit.",
    },
    "survival": {
        "expert": "Track any creature across any terrain (including stone and water) within 48 hours. Navigate without landmarks. Camp setup grants +2 HP to everyone's short rest.",
        "master": "Apex Predator — In wilderness, you choose where encounters happen (never ambushed, always ambush others). Track trails up to a week old across any surface. DM automatically reveals what passed through an area and when.",
    },
    "insight": {
        "expert": "Detect lies automatically — DM signals when an NPC lies without a check (you don't know the truth, just that the statement was false). Read emotional states with precision.",
        "master": "Empathic Clarity — Know the true motivation of any NPC you converse with for 30+ seconds. Not surface emotions, but core drive. DM reveals: 'They want X, and they're willing to Y to get it.'",
    },
    "animal_handling": {
        "expert": "Calm hostile natural animals without check (unless magically enraged). Command trained animals for complex multi-step tasks. Bond with a wild animal in a single encounter (follows you for session).",
        "master": "Beastfriend — Communicate with animals at basic conceptual level (intentions, emotions, simple ideas — not language). Bonded animals gain +2 to all rolls within earshot. Sense what nearby animals sense.",
    },
    "persuasion": {
        "expert": "Attempt to shift hostile NPCs to neutral. Negotiate beyond normal NPC parameters (better prices, unusual favors, restricted access).",
        "master": "Silver Tongue — Once per session, automatically succeed on a Persuasion check regardless of DC (impossible requests still fail). NPCs you've successfully persuaded remember you favorably: permanent +2 disposition.",
    },
    "deception": {
        "expert": "Maintain long-term false identities (sustained personas, not single lies). Plant false information NPCs spread to others. Lie under magical truth detection (Expert Deception vs detection DC).",
        "master": "Living Lie — Sustain up to 3 simultaneous false identities without checks. Discovery of one lie doesn't compromise others. Once per session, plant a false memory in an NPC through conversational manipulation (WIS save).",
    },
    "intimidation": {
        "expert": "Intimidate significantly stronger creatures without disadvantage. Demoralize groups: success against one enemy gives -1 to all their allies' next actions.",
        "master": "Terrifying Presence — At combat start, all enemies who see/hear you must WIS save or be Frightened 1 round (free, automatic). Once per session, end combat by Intimidation: all remaining enemies flee if combined HP < your max HP.",
    },
    "performance": {
        "expert": "Perform during combat for mechanical effect: grants all allies +1 to next roll (no Focus cost). Lasting impressions: NPCs who witness Expert performance gain permanent +2 disposition.",
        "master": "Legendary Performer — Performances are supernatural in impact without magic. Once per session: calm a riot, stop an NPC fight, cause an entire room to adopt an emotional state of your choice. Combat performance bonus increases to +2.",
    },
}

XP_FOR_LEVEL: dict[int, int] = {
    1: 0,
    2: 200,
    3: 450,
    4: 750,
    5: 1050,
    6: 1450,
    7: 1900,
    8: 2400,
    9: 2900,
    10: 3450,
    11: 4050,
    12: 4650,
    13: 5300,
    14: 6000,
    15: 6750,
    16: 7550,
    17: 8400,
    18: 9300,
    19: 10250,
    20: 11250,
}

MAX_LEVEL = 20
ATTRIBUTE_INCREASE_LEVELS: frozenset[int] = frozenset({4, 8, 12, 16, 20})
SPECIALIZATION_LEVEL: int = 5


@dataclass(frozen=True)
class LevelUpResult:
    new_xp: int
    new_level: int
    leveled_up: bool
    levels_gained: int
    attribute_points: int
    specialization_fork: bool


def check_level_up(current_xp: int, xp_gained: int, current_level: int) -> LevelUpResult:
    new_xp = current_xp + xp_gained
    new_level = current_level

    for lvl in range(current_level + 1, MAX_LEVEL + 1):
        if new_xp >= XP_FOR_LEVEL[lvl]:
            new_level = lvl
        else:
            break

    gained_levels = range(current_level + 1, new_level + 1)
    attribute_points = sum(2 for lvl in gained_levels if lvl in ATTRIBUTE_INCREASE_LEVELS)
    specialization_fork = SPECIALIZATION_LEVEL in gained_levels

    return LevelUpResult(
        new_xp=new_xp,
        new_level=new_level,
        leveled_up=new_level > current_level,
        levels_gained=new_level - current_level,
        attribute_points=attribute_points,
        specialization_fork=specialization_fork,
    )


# --- Core functions ---


def attribute_modifier(score: int) -> int:
    return (score - 10) // 2


def _get_skill_tier(player_data: dict, skill_lower: str) -> SkillTier:
    """Get the skill tier for a character, with fallback to proficiencies list."""
    skill_tiers = player_data.get("skill_tiers", {})
    if skill_lower in skill_tiers:
        return skill_tiers[skill_lower]
    proficiencies = player_data.get("proficiencies", [])
    if any(p.lower() == skill_lower for p in proficiencies):
        return "trained"
    return "untrained"


def skill_modifier(player_data: dict, skill: str) -> int:
    skill_lower = skill.lower()
    attr = SKILLS.get(skill_lower)
    if attr is None:
        raise ValueError(f"Unknown skill: '{skill}'")

    attributes = player_data.get("attributes", {})
    if isinstance(attr, tuple):
        mod = max(attribute_modifier(attributes.get(a, 10)) for a in attr)
    else:
        mod = attribute_modifier(attributes.get(attr, 10))

    tier = _get_skill_tier(player_data, skill_lower)
    mod += SKILL_TIER_BONUS[tier]

    if tier != "untrained":
        level = player_data.get("level", 1)
        mod += proficiency_bonus(level)

    return mod


def dc_for_tier(tier: DcTier | str) -> int:
    """Look up DC value for a difficulty tier. Raises ValueError on unknown tiers."""
    normalized = tier.lower()
    if normalized not in DC_TIERS:
        raise ValueError(f"Unknown difficulty tier: '{tier}'. Valid: {sorted(set(DC_TIERS.keys()) - {'deadly'})}")
    return DC_TIERS[normalized]


def narrative_hint(roll: int, total: int, dc: int) -> str:
    if roll == 1:
        return "critical failure"
    if roll == 20:
        return "critical success"

    margin = total - dc
    if margin < -5:
        return "failed"
    if margin < 0:
        return "barely failed"
    if margin == 0:
        return "barely succeeded"
    if margin <= 5:
        return "succeeded comfortably"
    return "succeeded overwhelmingly"
