"""Pure-function rules engine. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass
from typing import Literal

from dice import roll as dice_roll

# --- Type aliases ---

SkillTier = Literal["untrained", "trained", "expert", "master"]
DcTier = Literal["trivial", "easy", "moderate", "hard", "very_hard", "extreme", "legendary"]

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
    2: 300,
    3: 900,
    4: 2700,
    5: 6500,
    6: 14000,
    7: 23000,
    8: 34000,
    9: 48000,
    10: 64000,
    11: 85000,
    12: 100000,
    13: 120000,
    14: 140000,
    15: 165000,
    16: 195000,
    17: 225000,
    18: 265000,
    19: 305000,
    20: 355000,
}

MAX_LEVEL = 20


@dataclass(frozen=True)
class LevelUpResult:
    new_xp: int
    new_level: int
    leveled_up: bool
    levels_gained: int


def check_level_up(current_xp: int, xp_gained: int, current_level: int) -> LevelUpResult:
    new_xp = current_xp + xp_gained
    new_level = current_level

    for lvl in range(current_level + 1, MAX_LEVEL + 1):
        if new_xp >= XP_FOR_LEVEL[lvl]:
            new_level = lvl
        else:
            break

    return LevelUpResult(
        new_xp=new_xp,
        new_level=new_level,
        leveled_up=new_level > current_level,
        levels_gained=new_level - current_level,
    )


# --- Result dataclasses ---


@dataclass(frozen=True)
class CheckResult:
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    auto_fail: bool
    margin: int
    critical_success: bool
    critical_failure: bool
    narrative_hint: str


@dataclass(frozen=True)
class AdvancementResult:
    skill: str
    new_use_count: int
    advanced: bool
    old_tier: str
    new_tier: str
    narrative_cue: str


@dataclass(frozen=True)
class SkillCapabilities:
    skill: str
    tier: str
    expert_unlock: str | None
    master_unlock: str | None


@dataclass(frozen=True)
class SkillCheckResult:
    skill: str
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    margin: int
    narrative_hint: str


@dataclass(frozen=True)
class AttackResult:
    hit: bool
    roll: int
    attack_modifier: int
    attack_total: int
    target_ac: int
    damage: int
    damage_type: str
    critical: bool
    target_hp_remaining: int
    target_killed: bool
    narrative_hint: str


@dataclass(frozen=True)
class SavingThrowResult:
    save_type: str
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    margin: int
    effect_applied: str | None
    narrative_hint: str


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
    return "critical success"


def record_skill_use(
    skill_tiers: dict[str, SkillTier],
    skill: str,
    use_counters: dict[str, int],
    narrative_moment: bool = False,
) -> AdvancementResult:
    """Record a skill use and check for tier advancement. Pure function.

    Args:
        skill_tiers: Current tier per skill (e.g. {"athletics": "trained"}).
        skill: The skill being used (lowercase).
        use_counters: Current use counts per skill.
        narrative_moment: Whether DM has flagged a qualifying moment (Expert→Master gate).
    """
    skill_lower = skill.lower()
    if skill_lower not in SKILLS:
        raise ValueError(f"Unknown skill: '{skill}'")

    current_tier = skill_tiers.get(skill_lower, "untrained")
    new_count = use_counters.get(skill_lower, 0) + 1

    threshold = ADVANCEMENT_THRESHOLDS.get(current_tier)
    if threshold is not None and new_count >= threshold:
        if current_tier == "expert" and not narrative_moment:
            return AdvancementResult(
                skill=skill_lower,
                new_use_count=new_count,
                advanced=False,
                old_tier=current_tier,
                new_tier=current_tier,
                narrative_cue="",
            )
        tier_idx = SKILL_TIER_ORDER.index(current_tier)
        new_tier = SKILL_TIER_ORDER[tier_idx + 1]
        return AdvancementResult(
            skill=skill_lower,
            new_use_count=new_count,
            advanced=True,
            old_tier=current_tier,
            new_tier=new_tier,
            narrative_cue=f"Your {skill_lower.replace('_', ' ').title()} skill has advanced to {new_tier.title()}!",
        )

    return AdvancementResult(
        skill=skill_lower,
        new_use_count=new_count,
        advanced=False,
        old_tier=current_tier,
        new_tier=current_tier,
        narrative_cue="",
    )


def check_skill_capabilities(skill: str, tier: SkillTier) -> SkillCapabilities:
    """Return available capabilities for a skill at the given tier. Pure function."""
    skill_lower = skill.lower()
    if skill_lower not in SKILLS:
        raise ValueError(f"Unknown skill: '{skill}'")

    rank = SKILL_TIER_ORDER.index(tier)
    expert_rank = SKILL_TIER_ORDER.index("expert")
    master_rank = SKILL_TIER_ORDER.index("master")

    caps = SKILL_CAPABILITIES[skill_lower]
    return SkillCapabilities(
        skill=skill_lower,
        tier=tier,
        expert_unlock=caps["expert"] if rank >= expert_rank else None,
        master_unlock=caps["master"] if rank >= master_rank else None,
    )


_TIER_RANK: dict[str, int] = {tier: i for i, tier in enumerate(SKILL_TIER_ORDER)}
_EXPERT_RANK = _TIER_RANK["expert"]
_MASTER_RANK = _TIER_RANK["master"]


def _check_auto_fail(dc: int, skill_tier: SkillTier) -> bool:
    """Return True if the DC is beyond the character's tier gate."""
    rank = _TIER_RANK[skill_tier]
    if dc >= 28 and rank < _MASTER_RANK:
        return True
    return dc >= 24 and rank < _EXPERT_RANK


def resolve_check(
    attribute_score: int,
    level: int,
    skill_tier: SkillTier,
    dc: int,
    *,
    rng: random.Random | None = None,
) -> CheckResult:
    """Unified d20 resolution. Pure function, no IO.

    Args:
        attribute_score: Raw attribute value (e.g. 14 for STR 14).
        level: Character level (1-20).
        skill_tier: One of "untrained", "trained", "expert", "master".
        dc: Difficulty class to beat.
        rng: Optional seeded RNG for deterministic testing.
    """
    attr_mod = attribute_modifier(attribute_score)
    tier_bonus = SKILL_TIER_BONUS[skill_tier]

    prof = 0 if skill_tier == "untrained" else proficiency_bonus(level)

    total_mod = attr_mod + prof + tier_bonus

    if _check_auto_fail(dc, skill_tier):
        return CheckResult(
            roll=0,
            modifier=total_mod,
            total=0,
            dc=dc,
            success=False,
            auto_fail=True,
            margin=-dc,
            critical_success=False,
            critical_failure=False,
            narrative_hint="This task is beyond your current ability",
        )

    result = dice_roll("d20", rng=rng)
    d20 = result.total
    total = d20 + total_mod

    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc

    return CheckResult(
        roll=d20,
        modifier=total_mod,
        total=total,
        dc=dc,
        success=success,
        auto_fail=False,
        margin=total - dc,
        critical_success=d20 == 20,
        critical_failure=d20 == 1,
        narrative_hint=narrative_hint(d20, total, dc),
    )


def attack_modifier(player_data: dict, weapon: dict) -> int:
    attributes = player_data.get("attributes", {})
    finesse = "finesse" in weapon.get("properties", [])

    if finesse:
        str_mod = attribute_modifier(attributes.get("strength", 10))
        dex_mod = attribute_modifier(attributes.get("dexterity", 10))
        attr_mod = max(str_mod, dex_mod)
    elif weapon.get("ranged", False):
        attr_mod = attribute_modifier(attributes.get("dexterity", 10))
    else:
        attr_mod = attribute_modifier(attributes.get("strength", 10))

    level = player_data.get("level", 1)
    return attr_mod + proficiency_bonus(level)


# --- Resolution functions ---


def _resolve_skill_check_impl(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    skill_lower = skill.lower()
    attr = SKILLS.get(skill_lower)
    if attr is None:
        raise ValueError(f"Unknown skill: '{skill}'")

    attributes = player_data.get("attributes", {})
    score = max(attributes.get(a, 10) for a in attr) if isinstance(attr, tuple) else attributes.get(attr, 10)

    level = player_data.get("level", 1)
    tier = _get_skill_tier(player_data, skill_lower)

    check = resolve_check(score, level, tier, dc, rng=rng)

    return SkillCheckResult(
        skill=skill_lower,
        roll=check.roll,
        modifier=check.modifier,
        total=check.total,
        dc=check.dc,
        success=check.success,
        margin=check.margin,
        narrative_hint=check.narrative_hint,
    )


def resolve_skill_check(
    player_data: dict,
    skill: str,
    difficulty: str,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    return _resolve_skill_check_impl(player_data, skill, dc_for_tier(difficulty), rng)


def resolve_skill_check_dc(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    """Like resolve_skill_check but accepts a numeric DC directly.

    Use when the DC is stored as a number (e.g. hidden element DCs)
    rather than a difficulty tier string.
    """
    return _resolve_skill_check_impl(player_data, skill, dc, rng)


def resolve_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    target_hp: int,
    rng: random.Random | None = None,
) -> AttackResult:
    atk_mod = attack_modifier(attacker_data, weapon)
    hit_roll = dice_roll("d20", rng=rng)
    d20 = hit_roll.total
    attack_total = d20 + atk_mod

    critical = d20 == 20
    auto_miss = d20 == 1

    if auto_miss:
        hit = False
    elif critical:
        hit = True
    else:
        hit = attack_total >= target_ac

    damage = 0
    damage_type = weapon.get("damage_type", "bludgeoning")

    if hit:
        damage_notation = weapon.get("damage", "1d4")
        damage_result = dice_roll(damage_notation, rng=rng)
        damage = damage_result.total
        if critical:
            crit_result = dice_roll(damage_notation, rng=rng)
            damage += crit_result.total

    new_hp = max(0, target_hp - damage)

    return AttackResult(
        hit=hit,
        roll=d20,
        attack_modifier=atk_mod,
        attack_total=attack_total,
        target_ac=target_ac,
        damage=damage,
        damage_type=damage_type,
        critical=critical,
        target_hp_remaining=new_hp,
        target_killed=new_hp == 0 and hit,
        narrative_hint=narrative_hint(d20, attack_total, target_ac),
    )


# --- Combat dataclasses ---


@dataclass(frozen=True)
class InitiativeEntry:
    participant_id: str
    name: str
    roll: int
    modifier: int
    total: int


@dataclass(frozen=True)
class DeathSaveResult:
    roll: int
    success: bool
    critical_success: bool
    critical_failure: bool
    total_successes: int
    total_failures: int
    stabilized: bool
    dead: bool
    narrative_hint: str


# --- Combat functions ---


def roll_initiative(
    participants: list[dict],
    rng: random.Random | None = None,
) -> list[InitiativeEntry]:
    """Roll initiative for all participants. Returns sorted descending by total.

    Each participant dict must have: id, name, attributes.dexterity (or dexterity).
    """
    entries: list[InitiativeEntry] = []
    for p in participants:
        attrs = p.get("attributes", {})
        dex = attrs.get("dexterity", p.get("dexterity", 10))
        mod = attribute_modifier(dex)
        result = dice_roll("d20", rng=rng)
        d20 = result.total
        entries.append(
            InitiativeEntry(
                participant_id=p["id"],
                name=p.get("name", p["id"]),
                roll=d20,
                modifier=mod,
                total=d20 + mod,
            )
        )
    entries.sort(key=lambda e: e.total, reverse=True)
    return entries


def resolve_death_save(
    current_successes: int,
    current_failures: int,
    rng: random.Random | None = None,
) -> DeathSaveResult:
    """Resolve a death saving throw.

    Rules: 10+ = success, <10 = failure. Nat 20 = regain 1 HP (critical success).
    Nat 1 = two failures. 3 successes = stabilized, 3 failures = dead.
    """
    result = dice_roll("d20", rng=rng)
    d20 = result.total

    critical_success = d20 == 20
    critical_failure = d20 == 1
    success = d20 >= 10

    new_successes = current_successes
    new_failures = current_failures

    if critical_success:
        new_successes = current_successes + 1
        hint = "The faintest spark of life flares back — eyes open, breath returns"
    elif critical_failure:
        new_failures = current_failures + 2
        hint = "A violent shudder — the thread of life frays dangerously"
    elif success:
        new_successes = current_successes + 1
        hint = "A shallow breath, clinging to life"
    else:
        new_failures = current_failures + 1
        hint = "Slipping further into darkness"

    stabilized = new_successes >= 3
    dead = new_failures >= 3

    return DeathSaveResult(
        roll=d20,
        success=success,
        critical_success=critical_success,
        critical_failure=critical_failure,
        total_successes=new_successes,
        total_failures=new_failures,
        stabilized=stabilized,
        dead=dead,
        narrative_hint=hint,
    )


def hp_threshold_status(current_hp: int, max_hp: int) -> str:
    """Return a status string based on HP percentage.

    healthy (>50%), bloodied (<=50%), critical (<=25%), fallen (0).
    """
    if current_hp <= 0:
        return "fallen"
    ratio = current_hp / max_hp
    if ratio <= 0.25:
        return "critical"
    if ratio <= 0.5:
        return "bloodied"
    return "healthy"


def calculate_combat_xp(enemies: list[dict]) -> int:
    """Sum xp_value from a list of enemy dicts. Defaults to 0 if missing."""
    return sum(e.get("xp_value", 0) for e in enemies)


def resolve_saving_throw(
    player_data: dict,
    save_type: str,
    dc: int,
    effect_on_fail: str,
    rng: random.Random | None = None,
) -> SavingThrowResult:
    save_lower = save_type.lower()
    valid_saves = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
    if save_lower not in valid_saves:
        raise ValueError(f"Unknown save type: '{save_type}'")

    attributes = player_data.get("attributes", {})
    score = attributes.get(save_lower, 10)
    mod = attribute_modifier(score)

    save_proficiencies = player_data.get("saving_throw_proficiencies", [])
    if any(p.lower() == save_lower for p in save_proficiencies):
        level = player_data.get("level", 1)
        mod += proficiency_bonus(level)

    result = dice_roll("d20", rng=rng)
    d20 = result.total
    total = d20 + mod

    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc

    return SavingThrowResult(
        save_type=save_lower,
        roll=d20,
        modifier=mod,
        total=total,
        dc=dc,
        success=success,
        margin=total - dc,
        effect_applied=None if success else effect_on_fail,
        narrative_hint=narrative_hint(d20, total, dc),
    )
