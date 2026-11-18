"""The `check` verb (skill/social/discover/save/dice/gather kinds) + skill-breakthrough tool.

`check(roll)` is the consolidated uncertain-action verb (M5, ADR 0007, Verbs &
Stages §7/§10): it folds request_skill_check, discover_hidden_element,
request_saving_throw, and roll_dice into one kind-discriminated tool, dispatching to
per-mode sub-impls. The kinds are a sum type (`check_payloads.CheckPayload`, ADR 0008)
rather than ten optional parameters, so the verb costs one union slot instead of nine.
Resolution math lives in check_resolution.py / dice.py (reused unchanged).
`mark_skill_breakthrough` stays as its own tool.

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose `*_mod=`
keyword seams for TEST-ONLY injection; production uses the `@function_tool` wrapper.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_payloads
import check_resolution_save
import condition_voice_rules
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_mutations_skill_advancement
import db_queries
import dice
import event_types as E
import rules_engine
from check_discovery import _check_discover_impl
from check_payloads import CheckPayload
from check_skill import _check_skill_run
from condition_consume import consume_beneficial_conditions, serialize_combat_check
from db_errors import db_tool, validated_player_conditions
from game_events import publish_game_event
from gathering_tools import _check_gather_impl
from session_data import SessionData
from skill_check_effects import SkillCheckEffects
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
    roll: CheckPayload,
) -> str:
    """Resolve an uncertain action with a dice roll.

    Pass one roll object, picked by its kind: "skill" (the player attempts something
    risky), "social" (sway a specific NPC), "discover" (search or examine a visible
    thing), "save" (an effect forces the player to resist), "dice" (a narrative-only
    random moment), or "gather" (forage at the current location). Each kind's fields
    describe themselves. Successful Stealth conceals the acting player. Call another
    Stealth check when a watcher might notice, using that watcher's difficulty;
    failure reveals the player. Casting or attacking also ends concealment.

    Narrate the result from narrative_hint / narrative_cue. Never speak raw numbers or DCs."""
    mode, kwargs = check_payloads.to_impl_args(roll)
    return await _check_impl(context, mode, **kwargs)


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
    hearing_only: bool = False,
    *,
    queries=db_queries,
    mutations=db_mutations,
    skill_mutations=db_mutations_skill_advancement,
    content=db_content_queries,
) -> str:
    if mode == "skill":
        return await _check_skill_impl(
            context,
            skill,
            difficulty,
            context_description,
            hearing_only=hearing_only,
            queries=queries,
            mutations=skill_mutations,
        )
    if mode == "social":
        return await _check_social_impl(
            context, npc_id, skill, difficulty, queries=queries, mutations=mutations, content=content
        )
    if mode == "discover":
        return await _check_discover_impl(
            context, skill, target, hearing_only=hearing_only, content=content, queries=queries, mutations=mutations
        )
    if mode == "save":
        return await _check_save_impl(context, save_type, dc, effect_on_fail, queries=queries)
    if mode == "dice":
        return await _check_dice_impl(context, notation)
    if mode == "gather":
        return await _check_gather_impl(context, target, queries=queries, mutations=mutations, content=content)
    raise ToolError(f"Unknown check mode {mode!r}; expected one of: {', '.join(VALID_CHECK_MODES)}.")


@serialize_combat_check
async def _check_skill_impl(
    context: RunContext[SessionData],
    skill: str,
    difficulty: str,
    context_description: str,
    *,
    hearing_only: bool = False,
    queries=db_queries,
    mutations=db_mutations_skill_advancement,
    db_mod=db,
    conditions_mutations=db_mutations_conditions,
) -> str:
    effects = SkillCheckEffects()
    async with db_mod.transaction() as conn:
        response = await _check_skill_run(
            context,
            skill,
            difficulty,
            context_description,
            hearing_only=hearing_only,
            queries=queries,
            mutations=mutations,
            db_mod=db_mod,
            conditions_mutations=conditions_mutations,
            conn=conn,
            effects=effects,
        )
    await effects.flush(context.userdata, publish=publish_game_event)
    return response


@serialize_combat_check
async def _check_save_impl(
    context: RunContext[SessionData],
    save_type: str,
    dc: int,
    effect_on_fail: str,
    *,
    queries=db_queries,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
) -> str:
    logger.info("check save: save_type=%s, dc=%d, effect_on_fail=%s", save_type, dc, effect_on_fail)
    _cap_str(effect_on_fail, 256, "effect_on_fail")
    if dc < 1 or dc > 30:
        raise ToolError("DC must be between 1 and 30.")
    session: SessionData = context.userdata

    player_id = session.acting_player_id
    player = await queries.get_player(player_id)
    if player is None:
        raise ToolError(f"Player '{player_id}' not found.")
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, player_id)

    try:
        result = check_resolution_save.resolve_saving_throw(
            condition_voice_rules.roll_data(player, session.combat_state, player_id), save_type, dc, effect_on_fail
        )
    except ValueError as e:
        raise ToolError(str(e)) from e

    # Consume the single-use beneficial die (M4.8 story-003): a player-initiated save spends Blessed/
    # Inspired's +1d4, so remove the signalled conditions and persist. One write (no competing
    # mutation here), so no transaction is needed.
    consumed_state = None
    if result.consumed_conditions:
        session.validate_acting_player(player_id)
        consumed_state = await consume_beneficial_conditions(
            player_id,
            result.consumed_conditions,
            conditions_mutations,
            combat_state=session.combat_state,
            db_mod=db_mod,
        )

    if consumed_state is not None:
        session.combat_state = consumed_state

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
    mutations=db_mutations_skill_advancement,
) -> str:
    session: SessionData = context.userdata
    skill_lower = skill.lower()

    if skill_lower not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    await mutations.mark_narrative_moment(session.acting_player_id, skill_lower)
    logger.info("mark_skill_breakthrough: player=%s, skill=%s", session.acting_player_id, skill_lower)
    return json.dumps({"status": "ok", "skill": skill_lower, "narrative_moment_ready": True})
