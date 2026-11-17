"""Skill resolution shared by ordinary checks and patron rerolls."""

import json
import logging
from contextlib import nullcontext

from livekit.agents.llm import ToolError

import check_resolution
import choir_scene
import concealment
import condition_voice_rules
import event_types as E
import rules_engine
import skill_persistence
from combat_terrain import skill_natural_terrain
from condition_consume import consume_beneficial_conditions
from condition_voice_rules import validate_hearing_check
from db_errors import validated_player_conditions
from patron_gift_tools import offer
from patron_gifts import KNOWLEDGE_SKILLS
from session_data import SessionData
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")
VALID_SKILLS = set(rules_engine.SKILLS)
VALID_DIFFICULTIES = set(rules_engine.DC_TIERS)


async def _check_skill_run(
    context,
    skill,
    difficulty,
    context_description,
    *,
    hearing_only,
    queries,
    mutations,
    db_mod,
    conditions_mutations,
    effects,
    conn=None,
    locked_player=None,
    reroll_dc=None,
):
    try:
        validate_hearing_check(skill, hearing_only)
    except ValueError as e:
        raise ToolError(str(e)) from e
    logger.info("check skill: skill=%s, difficulty=%s, context=%s", skill, difficulty, context_description)
    _cap_str(context_description, 500, "context_description")
    session: SessionData = context.userdata

    if skill.lower() not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    if difficulty.lower() not in VALID_DIFFICULTIES:
        raise ToolError(f"Unknown difficulty: '{difficulty}'. Valid: {sorted(VALID_DIFFICULTIES - {'deadly'})}")

    player_id = session.acting_player_id
    player = locked_player or (
        await queries.get_player(player_id, conn=conn, for_update=True)
        if conn is not None
        else await queries.get_player(player_id)
    )
    if player is None:
        raise ToolError(f"Player '{player_id}' not found.")
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, player_id)
    player = await choir_scene.check_data(session, player, queries=queries)

    resolver = check_resolution.resolve_skill_check if reroll_dc is None else check_resolution.resolve_skill_check_dc
    result = resolver(
        condition_voice_rules.roll_data(player, session.combat_state, player_id),
        skill,
        difficulty if reroll_dc is None else reroll_dc,
        ally_present=session.ally_present_for(player_id),
        natural_terrain=await skill_natural_terrain(session, player, skill),
        hearing_only=hearing_only,
    )

    concealment_packet = None
    if skill.lower() == "stealth":
        session.validate_acting_player(player_id)
        concealment_packet = await concealment.transition(
            player, result.success, ended_by=None if result.success else "failed_stealth", conn=conn
        )
        concealment_packet["guidance"] = "Call Stealth again when a watcher might notice; failure reveals this player."

    if result.auto_fail:
        return json.dumps(
            {
                **({"concealment": concealment_packet} if concealment_packet else {}),
                "outcome": "automatic_failure",
                "skill": result.skill,
                "roll": 0,
                "narrative_hint": result.narrative_hint,
                "context": context_description,
            }
        )

    effects.events.append(
        (
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
        )
    )

    consumed_state = None
    adv = None
    if result.consumed_conditions:
        async with nullcontext(conn) if conn is not None else db_mod.transaction() as write_conn:
            session.validate_acting_player(player_id)
            if reroll_dc is None:
                adv = await skill_persistence.apply_skill_use_with_persistence(
                    player_id,
                    skill,
                    counter_increment=1,
                    initial_tier=rules_engine._get_skill_tier(player, skill.lower()),
                    conn=write_conn,
                    queries=queries,
                    mutations=mutations,
                )
            consumed_state = await consume_beneficial_conditions(
                player_id,
                result.consumed_conditions,
                conditions_mutations,
                conn=write_conn,
                combat_state=session.combat_state,
                db_mod=db_mod,
            )
    elif reroll_dc is None:
        session.validate_acting_player(player_id)
        adv = await skill_persistence.apply_skill_use_with_persistence(
            player_id,
            skill,
            counter_increment=1,
            initial_tier=rules_engine._get_skill_tier(player, skill.lower()),
            conn=conn,
            queries=queries,
            mutations=mutations,
        )

    effects.combat_state = consumed_state
    if adv is not None and adv.advanced:
        effects.events.append(
            (
                E.SKILL_TIER_ADVANCED,
                {"skill": adv.skill, "old_tier": adv.old_tier, "new_tier": adv.new_tier},
            )
        )

    outcome = "success" if result.success else "failure"
    effects.recent_event = f"Skill check ({skill}, {difficulty}): {outcome}"

    response = {
        **({"concealment": concealment_packet} if concealment_packet else {}),
        "outcome": outcome,
        "skill": result.skill,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "margin": result.margin,
        "narrative_hint": result.narrative_hint,
        "context": context_description,
        **({"gift_name": result.gift_name} if result.gift_name else {}),
    }
    if reroll_dc is None and skill.lower() in KNOWLEDGE_SKILLS:
        offered = await offer(
            session,
            player,
            result,
            {
                "kind": "skill",
                "skill": skill.lower(),
                "dc": result.dc,
                "difficulty": difficulty,
                "context_description": context_description,
                "hearing_only": hearing_only,
                "location_id": session.location_id,
            },
            conn=conn,
        )
        if offered:
            response["reroll_offer"] = offered
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
