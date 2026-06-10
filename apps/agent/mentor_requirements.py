"""Mentor training-requirement checks (M6.3 / story-002).

Read-only gating for learn(variant): given (player_id, mentor_id, variant_id), read
the mentor's mentor{} training block (story-001) and report whether the player meets
its disposition/quest/gold/skill requirements, with a specific unmet list. No DB
mutations. Mirrors disposition.resolve_disposition — async with injectable *_mod seams
so callers and tests thread their own mocks through.

The single mentor{} block gates ALL of that mentor's variants (decision
mentor-binding-shape); variant_id is validated to belong to the mentor, then the
mentor-level requirements apply.
"""

from dataclasses import dataclass

import db_content_queries
import db_queries
import disposition
import mentor_variants
from role_archetypes import DISPOSITIONS
from rules_engine import SKILL_TIER_ORDER, SKILLS


@dataclass(frozen=True)
class MentorRequirementsResult:
    met: bool
    unmet: list[str]  # human-readable failed-gate labels; empty when met


def _parse_skill_requirement(skill: str) -> tuple[str, str]:
    """Parse a "SkillName: Tier" requirement into (skill_id, tier), both canonical
    lowercase. Fails loud on a malformed string, unknown skill, or unknown tier —
    story-001's conformance test enforces this shape, so live content never trips it."""
    name, sep, tier = skill.partition(":")
    skill_id = name.strip().lower()
    tier = tier.strip().lower()
    if not sep or not skill_id or skill_id not in SKILLS:
        raise ValueError(f"mentor skill requirement {skill!r} is not a known 'SkillName: Tier'")
    if tier not in SKILL_TIER_ORDER:
        raise ValueError(f"mentor skill requirement {skill!r} has unknown tier {tier!r}")
    return skill_id, tier


def _skill_tier_meets(have_tier: str, required_tier: str) -> bool:
    return SKILL_TIER_ORDER.index(have_tier) >= SKILL_TIER_ORDER.index(required_tier)


async def _evaluate_skill(player_id, skill_requirement, *, conn, queries_mod) -> tuple[bool, str]:
    """Parse the "SkillName: Tier" requirement, read the player's advancement once, and
    report (meets_requirement, have_tier). A skill with no advancement row is 'untrained'.
    Single source for both the boolean check_skill_tier and the unmet-label aggregate."""
    skill_id, required_tier = _parse_skill_requirement(skill_requirement)
    advancement = await queries_mod.get_skill_advancement(player_id, conn=conn)
    have_tier = advancement.get(skill_id, {}).get("tier", "untrained")
    return _skill_tier_meets(have_tier, required_tier), have_tier


async def check_quest_completed(player_id, quest_id, *, conn=None, queries_mod=db_queries) -> bool:
    """True iff the player has a player_quests row for quest_id with status 'complete'."""
    player_quest = await queries_mod.get_player_quest(player_id, quest_id, conn=conn)
    return player_quest is not None and player_quest.get("status", "active") == "complete"


async def check_skill_tier(player_id, skill_requirement, *, conn=None, queries_mod=db_queries) -> bool:
    """True iff the player's tier in the required skill is at or above the requirement.
    A player with no advancement row for the skill is treated as 'untrained' (rank 0)."""
    met, _ = await _evaluate_skill(player_id, skill_requirement, conn=conn, queries_mod=queries_mod)
    return met


async def check_mentor_requirements(
    player_id,
    mentor_id,
    variant_id,
    *,
    conn=None,
    queries_mod=db_queries,
    content_mod=db_content_queries,
    variants_mod=mentor_variants,
    disposition_mod=disposition,
) -> MentorRequirementsResult:
    """Whether the player meets mentor_id's training requirements for variant_id.

    Validates variant_id is taught by mentor_id (fail-loud ValueError otherwise — a
    usage error, not a player-fixable gate), reads the mentor's mentor{} requirements,
    and checks disposition/quest/gold/skill. Returns met + a specific unmet list.
    Read-only; the caller (story-003) maps ValueError and unmet to ToolError.
    """
    variant = variants_mod.get_mentor_variant(variant_id)  # raises ValueError if unknown
    if variant.mentor_id != mentor_id:
        raise ValueError(f"variant {variant_id!r} is taught by {variant.mentor_id!r}, not {mentor_id!r}")

    npc = await content_mod.get_npc(mentor_id)
    if npc is None or "mentor" not in npc:
        raise ValueError(f"NPC {mentor_id!r} has no mentor training block")
    req = npc["mentor"]["requirements"]

    unmet: list[str] = []

    standing = await disposition_mod.resolve_disposition(
        mentor_id, player_id, conn=conn, queries_mod=queries_mod, content_mod=content_mod
    )
    if DISPOSITIONS.index(standing) < DISPOSITIONS.index(req["disposition"]):
        unmet.append(f"disposition: need {req['disposition']}, have {standing}")

    quest_id = req.get("quest")
    if quest_id is not None and not await check_quest_completed(
        player_id, quest_id, conn=conn, queries_mod=queries_mod
    ):
        unmet.append(f"quest: complete '{quest_id}' first")

    player = await queries_mod.get_player(player_id, conn=conn)
    gold = player.get("gold", 0) if player else 0
    if gold < req["gold"]:
        unmet.append(f"gold: need {req['gold']}, have {gold}")

    skill = req.get("skill")
    if skill is not None:
        met, have_tier = await _evaluate_skill(player_id, skill, conn=conn, queries_mod=queries_mod)
        if not met:
            unmet.append(f"skill: need {skill}, have {have_tier}")

    return MentorRequirementsResult(met=not unmet, unmet=unmet)
