"""Pure skill advancement and tier capabilities."""

from dataclasses import dataclass

from rules_engine import ADVANCEMENT_THRESHOLDS, SKILL_CAPABILITIES, SKILL_TIER_ORDER, SKILLS, SkillTier


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
