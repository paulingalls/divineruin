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
import patron_deeds
import rules_engine
import skill_persistence
import zhael_fate
from combat_terrain import skill_natural_terrain
from condition_consume import consume_beneficial_conditions
from condition_voice_rules import validate_hearing_check
from db_errors import validated_player_conditions
from patron_gifts import KNOWLEDGE_SKILLS
from patron_location import check_first_stay
from session_data import SessionData
from skill_check_effects import SkillCheckEffects
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
        ally_present=session.allies_present_for(player_id),
        first_stay=await check_first_stay(player, session, skill, conn=conn),
        natural_terrain=await skill_natural_terrain(session, player, skill),
        hearing_only=hearing_only,
    )

    d20 = result.d20
    if reroll_dc is None and d20 is not None:
        candidates = await zhael_fate.candidates(session, queries=queries, conn=conn, roller=(player_id, player))
        location_id = session.location_id

        async def resume(kept):
            from check_tools import publish_game_event

            async with session.combat_state_lock:
                if player_id not in session.present_member_ids or session.location_id != location_id:
                    return zhael_fate.cancel(session, "The skill check's roller is no longer present for this check.")
                deferred = SkillCheckEffects()
                async with db_mod.transaction() as write_conn:
                    current = await queries.get_player(player_id, conn=write_conn, for_update=True)
                    if current is None:
                        raise ToolError(f"Player '{player_id}' not found.")
                    packet = await _finish_skill(
                        session,
                        player_id,
                        current,
                        kept,
                        skill,
                        difficulty,
                        context_description,
                        hearing_only=hearing_only,
                        queries=queries,
                        mutations=mutations,
                        db_mod=db_mod,
                        conditions_mutations=conditions_mutations,
                        effects=deferred,
                        conn=write_conn,
                        resumed=True,
                    )
                zhael_fate.effects_committed(session)
                await deferred.flush(session, publish=publish_game_event)
                return zhael_fate.Resumed(json.loads(packet))

        offer = zhael_fate.make_offer(
            "skill",
            player_id,
            result,
            candidates,
            numbers=lambda r: (r.roll, r.total),
            reroll=lambda: check_resolution.skill_with_roll(result, d20.roll()),
            flip=lambda face: check_resolution.skill_with_roll(result, d20.evaluate(face)),
            resume=resume,
        )
        if offer is not None:
            effects.fate_offer = offer
            return json.dumps(offer.response())

    return await _finish_skill(
        session,
        player_id,
        player,
        result,
        skill,
        difficulty,
        context_description,
        hearing_only=hearing_only,
        queries=queries,
        mutations=mutations,
        db_mod=db_mod,
        conditions_mutations=conditions_mutations,
        effects=effects,
        conn=conn,
        reroll_dc=reroll_dc,
    )


async def _finish_skill(
    session,
    player_id,
    player,
    result,
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
    conn,
    reroll_dc=None,
    resumed=False,
):
    def validate():
        if resumed:
            session.member_state(player_id)
        else:
            session.validate_acting_player(player_id)

    concealment_packet = None
    if skill.lower() == "stealth":
        validate()
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
            validate()
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
        validate()
        adv = await skill_persistence.apply_skill_use_with_persistence(
            player_id,
            skill,
            counter_increment=1,
            initial_tier=rules_engine._get_skill_tier(player, skill.lower()),
            conn=conn,
            queries=queries,
            mutations=mutations,
        )

    if result.success:
        skill_name = skill.lower()
        deed = (
            "successful_stealth"
            if skill_name == "stealth"
            else "discovered_lore"
            if skill_name in KNOWLEDGE_SKILLS
            else None
        )
        if deed is not None:
            assert conn is not None
            validate()
            await patron_deeds.record_deed(player_id, deed, conn=conn)

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
        from patron_gift_tools import offer

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
            authorized_roller=player_id if resumed else None,
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
