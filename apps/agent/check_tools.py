"""The `check` verb (skill/discover/save/dice modes) + skill-breakthrough tool.

`check(mode, ...)` is the consolidated uncertain-action verb (M5, ADR 0007, Verbs &
Stages §7/§10): it folds request_skill_check, discover_hidden_element,
request_saving_throw, and roll_dice into one mode-discriminated tool, dispatching to
per-mode sub-impls. Resolution math lives in check_resolution.py / dice.py (reused
unchanged). `mark_skill_breakthrough` stays as its own tool.

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose `*_mod=`
keyword seams for TEST-ONLY injection; production uses the `@function_tool` wrapper.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import check_resolution_save
import conditions
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_queries
import dice
import event_types as E
import rules_engine
import skill_persistence
from check_discovery import _check_discover_impl
from db_errors import db_tool, validated_player_conditions
from game_events import publish_game_event
from gathering_tools import _check_gather_impl
from session_data import SessionData
from social_tools import _check_social_impl
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")

VALID_SKILLS = set(rules_engine.SKILLS.keys())
VALID_DIFFICULTIES = set(rules_engine.DC_TIERS.keys())
VALID_CHECK_MODES = ("skill", "discover", "save", "dice", "social", "gather")


@function_tool()
@db_tool
async def check(
    context: RunContext[SessionData],
    mode: str,
    skill: str = "",
    target: str = "",
    difficulty: str = "",
    save_type: str = "",
    dc: int = 0,
    effect_on_fail: str = "",
    notation: str = "",
    context_description: str = "",
    npc_id: str = "",
) -> str:
    """Resolve an uncertain action with a dice roll. Pick a mode:

    - mode="skill": the player attempts something risky (climb, recall lore). Give
      skill, difficulty (trivial/easy/moderate/hard/very_hard/extreme/legendary),
      and context_description.
    - mode="social": the player tries to sway a specific NPC (persuade, deceive,
      intimidate). Give npc_id, skill (persuasion/deception/intimidation), and
      difficulty. The NPC's disposition shifts the DC and may change from the result.
    - mode="discover": the player searches or examines a visible thing. Give the
      skill (the approach, e.g. perception) and target (the visible feature being
      examined, e.g. notice_board). What is hidden — if anything — is revealed by
      the roll; never name the secret yourself.
    - mode="save": an effect forces the player to resist. Give save_type (an
      attribute), dc, and effect_on_fail.
    - mode="dice": a narrative-only random moment (weather, crowd size). Give notation.
    - mode="gather": the player forages for materials at their current location. Optionally
      give target as a material category (herbs/plant/wood, metals/stone/gems, arcane_components)
      to route the skill (Nature/Survival/Arcana); omit it for general foraging. A rich find may
      uncover and harvest a fixed resource node here.

    Narrate the result from narrative_hint / narrative_cue. Never speak raw numbers or DCs."""
    return await _check_impl(
        context, mode, skill, target, difficulty, save_type, dc, effect_on_fail, notation, context_description, npc_id
    )


async def _check_impl(
    context: RunContext[SessionData],
    mode: str,
    skill: str = "",
    target: str = "",
    difficulty: str = "",
    save_type: str = "",
    dc: int = 0,
    effect_on_fail: str = "",
    notation: str = "",
    context_description: str = "",
    npc_id: str = "",
    *,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
) -> str:
    if mode == "skill":
        return await _check_skill_impl(
            context, skill, difficulty, context_description, queries=queries, mutations=mutations
        )
    if mode == "social":
        return await _check_social_impl(
            context, npc_id, skill, difficulty, queries=queries, mutations=mutations, content=content
        )
    if mode == "discover":
        return await _check_discover_impl(context, skill, target, content=content, queries=queries, mutations=mutations)
    if mode == "save":
        return await _check_save_impl(context, save_type, dc, effect_on_fail, queries=queries)
    if mode == "dice":
        return await _check_dice_impl(context, notation)
    if mode == "gather":
        return await _check_gather_impl(context, target, queries=queries, mutations=mutations, content=content)
    raise ToolError(f"Unknown check mode {mode!r}; expected one of: {', '.join(VALID_CHECK_MODES)}.")


async def _consume_beneficial_conditions(player_id, player, consumed, conditions_mutations, *, conn=None):
    """Remove the beneficial conditions a roll consumed and persist the new list (M4.8 story-003).

    No-op when nothing was consumed. ``conn`` threads an open transaction so the removal commits
    atomically with a sibling write (the skill tool's tier-advancement); the save tool passes none
    (its only write). Reads the player's current conditions off the already-fetched row."""
    if not consumed:
        return
    new_conditions = player.get("conditions") or []
    for ctype in consumed:
        new_conditions = conditions.remove_condition(new_conditions, ctype)
    await conditions_mutations.save_player_conditions(player_id, new_conditions, conn=conn)


async def _check_skill_impl(
    context: RunContext[SessionData],
    skill: str,
    difficulty: str,
    context_description: str,
    *,
    queries=db_queries,
    mutations=db_mutations,
    db_mod=db,
    conditions_mutations=db_mutations_conditions,
) -> str:
    logger.info("check skill: skill=%s, difficulty=%s, context=%s", skill, difficulty, context_description)
    _cap_str(context_description, 500, "context_description")
    session: SessionData = context.userdata

    if skill.lower() not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    if difficulty.lower() not in VALID_DIFFICULTIES:
        raise ToolError(f"Unknown difficulty: '{difficulty}'. Valid: {sorted(VALID_DIFFICULTIES - {'deadly'})}")

    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, session.player_id)

    result = check_resolution.resolve_skill_check(player, skill, difficulty)

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "skill_check",
            "skill": result.skill,
            "roll": result.roll,
            "total": result.total,
            "success": result.success,
            "dramatic": result.dramatic,
            "context": result.context,
        },
        event_bus=session.event_bus,
    )

    # Track skill use for tier advancement (shared helper enforces M1.2 contract). When the check
    # consumed a beneficial die (M4.8 story-003), the advancement write AND the condition removal run
    # in ONE transaction so a half-applied check can't occur (concern 42c4e9c2a23b); the common
    # no-consume path keeps the single tx-free write exactly as before.
    if result.consumed_conditions:
        async with db_mod.transaction() as conn:
            adv = await skill_persistence.apply_skill_use_with_persistence(
                session.player_id, skill, counter_increment=1, conn=conn, queries=queries, mutations=mutations
            )
            await _consume_beneficial_conditions(
                session.player_id, player, result.consumed_conditions, conditions_mutations, conn=conn
            )
    else:
        adv = await skill_persistence.apply_skill_use_with_persistence(
            session.player_id, skill, counter_increment=1, queries=queries, mutations=mutations
        )

    if adv is not None and adv.advanced:
        await publish_game_event(
            session.room,
            E.SKILL_TIER_ADVANCED,
            {"skill": adv.skill, "old_tier": adv.old_tier, "new_tier": adv.new_tier},
            event_bus=session.event_bus,
        )

    outcome = "success" if result.success else "failure"
    session.record_event(f"Skill check ({skill}, {difficulty}): {outcome}")

    response = {
        "outcome": outcome,
        "skill": result.skill,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "margin": result.margin,
        "narrative_hint": result.narrative_hint,
        "context": context_description,
    }
    if adv is not None and adv.advanced:
        response["advancement"] = {
            "old_tier": adv.old_tier,
            "new_tier": adv.new_tier,
            "narrative_cue": adv.narrative_cue,
        }
    logger.info(
        "check skill result: d20=%d+%d=%d vs DC %d → %s (%s)",
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
        result.narrative_hint,
    )
    return json.dumps(response)


async def _check_save_impl(
    context: RunContext[SessionData],
    save_type: str,
    dc: int,
    effect_on_fail: str,
    *,
    queries=db_queries,
    conditions_mutations=db_mutations_conditions,
) -> str:
    logger.info("check save: save_type=%s, dc=%d, effect_on_fail=%s", save_type, dc, effect_on_fail)
    _cap_str(effect_on_fail, 256, "effect_on_fail")
    if dc < 1 or dc > 30:
        raise ToolError("DC must be between 1 and 30.")
    session: SessionData = context.userdata

    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, session.player_id)

    try:
        result = check_resolution_save.resolve_saving_throw(player, save_type, dc, effect_on_fail)
    except ValueError as e:
        raise ToolError(str(e)) from e

    # Consume the single-use beneficial die (M4.8 story-003): a player-initiated save spends Blessed/
    # Inspired's +1d4, so remove the signalled conditions and persist. One write (no competing
    # mutation here), so no transaction is needed.
    await _consume_beneficial_conditions(session.player_id, player, result.consumed_conditions, conditions_mutations)

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "saving_throw",
            "save_type": result.save_type,
            "roll": result.roll,
            "total": result.total,
            "success": result.success,
            "dramatic": result.dramatic,
            "context": result.context,
        },
        event_bus=session.event_bus,
    )

    outcome = "success" if result.success else "failure"
    session.record_event(f"Saving throw ({save_type} DC {dc}): {outcome}")

    response = {
        "outcome": outcome,
        "save_type": result.save_type,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "margin": result.margin,
        "effect_applied": result.effect_applied,
        "narrative_hint": result.narrative_hint,
    }
    logger.info(
        "check save result: d20=%d+%d=%d vs DC %d → %s (%s)",
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
        result.narrative_hint,
    )
    return json.dumps(response)


async def _check_dice_impl(
    context: RunContext[SessionData],
    notation: str,
) -> str:
    logger.info("check dice: notation=%s", notation)
    _cap_str(notation, 50, "notation")
    session: SessionData = context.userdata

    try:
        result = dice.roll(notation)
    except ValueError as e:
        logger.warning("check dice invalid notation: %s", notation)
        raise ToolError(str(e)) from e

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "narrative",
            "notation": result.notation,
            "total": result.total,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Rolled {notation}: {result.total}")

    return json.dumps(
        {
            "notation": result.notation,
            "rolls": result.rolls,
            "dropped": result.dropped,
            "total": result.total,
        }
    )


@function_tool()
@db_tool
async def mark_skill_breakthrough(
    context: RunContext[SessionData],
    skill: str,
) -> str:
    """Mark that the current player has achieved a narrative breakthrough
    moment for the specified skill. This enables Expert→Master advancement
    once the use counter threshold (40) is reached. Use when the player
    performs exceptionally on a skill during a high-stakes moment."""
    return await _mark_skill_breakthrough_impl(context, skill)


async def _mark_skill_breakthrough_impl(
    context: RunContext[SessionData],
    skill: str,
    *,
    mutations=db_mutations,
) -> str:
    session: SessionData = context.userdata
    skill_lower = skill.lower()

    if skill_lower not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    await mutations.mark_narrative_moment(session.player_id, skill_lower)
    logger.info("mark_skill_breakthrough: player=%s, skill=%s", session.player_id, skill_lower)
    return json.dumps({"status": "ok", "skill": skill_lower, "narrative_moment_ready": True})
