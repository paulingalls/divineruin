"""Social-encounter resolution for the `check` verb's mode="social" (M4.6a / story-002).

`_check_social_impl` is the IO half of social resolution: it reads the NPC's current
disposition, rolls the player's social skill, drives the pure `social_resolution` engine,
persists any disposition change, and returns a narration cue for the DM. It lives here
(imported by check_tools.py's dispatcher) the same way mode="discover" lives in
check_discovery.py — keeping the check verb lean. Resolution math is reused unchanged from
social_resolution.py / check_resolution.py; this module only does the plumbing + IO.
"""

import json
import logging
import random
from contextlib import nullcontext
from functools import partial

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import communication_voice_rules
import condition_voice_rules
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import rules_engine
import social_resolution
import zhael_foretold_words
from condition_consume import consume_beneficial_conditions, serialize_combat_check
from db_errors import validated_player_conditions
from disposition import resolve_disposition
from game_events import publish_game_event
from patron_synergy import has_engine_synergy
from session_data import SessionData
from skill_fate import SkillScope, StaleSkillOperation, prepare_skill_offer
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# The three CHA-based skills that shift NPC disposition (spec L678-685). Other skills go
# through mode="skill"; routing them here is a caller bug.
SOCIAL_SKILLS = ("persuasion", "deception", "intimidation")
VALID_DIFFICULTIES = set(rules_engine.DC_TIERS.keys())


@serialize_combat_check
async def _check_social_impl(
    context: RunContext[SessionData],
    npc_id: str,
    skill: str,
    difficulty: str,
    *,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
    rng: random.Random | None = None,
) -> str:
    logger.info("check social: npc=%s, skill=%s, difficulty=%s", npc_id, skill, difficulty)
    skill_lower = skill.lower()
    # npc_id is an entity identifier, not free text: validate charset + length at the
    # boundary the same way every other id-taking tool does (e.g. crafting_tools npc_id).
    _validate_id(npc_id, "npc_id")
    if skill_lower not in SOCIAL_SKILLS:
        raise ToolError(f"Unknown social skill: '{skill}'. Valid: {list(SOCIAL_SKILLS)}")
    if difficulty.lower() not in VALID_DIFFICULTIES:
        raise ToolError(f"Unknown difficulty: '{difficulty}'. Valid: {sorted(VALID_DIFFICULTIES - {'deadly'})}")

    session: SessionData = context.userdata
    player_id = session.acting_player_id
    if session.combat_state is not None:
        try:
            communication_voice_rules.require_delivery(
                communication_voice_rules.CommunicationKind.SPOKEN, session.combat_state, player_id, [npc_id]
            )
        except ValueError as e:
            raise ToolError(str(e)) from e
    player = await queries.get_player(player_id)
    if player is None:
        raise ToolError(f"Player '{player_id}' not found.")
    # Same read-boundary guard as the skill/save modes (M4.4 story-008): a corrupt conditions
    # row otherwise reaches get_condition_effects as a raw KeyError, not a DM-narratable error.
    validated_player_conditions(player, player_id)

    try:
        communication_voice_rules.require_delivery(
            communication_voice_rules.CommunicationKind.SPOKEN,
            session.combat_state,
            player_id,
            [npc_id],
            rows={player_id: player},
        )
    except ValueError as e:
        raise ToolError(str(e)) from e

    session_id = session.session_id
    binding = (
        await zhael_foretold_words.pending(player_id, npc_id, session_id)
        if has_engine_synergy(player, zhael_foretold_words.CLAUSE)
        else None
    )
    if binding is not None and binding["skill"] != skill_lower:
        raise ToolError(f"Foretold Words binds the next check against {npc_id} to {binding['skill']}.")
    base_dc = rules_engine.dc_for_tier(difficulty.lower())
    roll = check_resolution.resolve_skill_check_dc(
        condition_voice_rules.roll_data(player, session.combat_state, player_id),
        skill_lower,
        binding["dc"] if binding is not None else base_dc,
        rng,
        ally_present=session.allies_present_for(player_id),
        natural_terrain=False,
        hearing_only=False,
    )
    scope = SkillScope.capture(session, player_id)

    finish = partial(
        _finish_social,
        session,
        player_id,
        npc_id,
        skill_lower,
        base_dc,
        session_id=session_id,
        binding=binding,
        queries=queries,
        content=content,
        mutations=mutations,
        conditions_mutations=conditions_mutations,
        db_mod=db_mod,
    )

    async def write(kept, conn):
        await scope.lock_roller(session, conn, queries=queries)
        return await finish(kept, conn=conn, scope=scope)

    offer = await prepare_skill_offer(session, scope, roll, player, write, queries=queries, db_mod=db_mod)
    if offer is not None:
        session.fate_offer = offer
        return json.dumps(offer.response())

    if binding is None:
        flush = await finish(roll)
    else:
        try:
            async with db_mod.transaction() as conn:
                locked_player = await queries.get_player(player_id, conn=conn, for_update=True)
                session.validate_acting_player(player_id)
                if locked_player is None:
                    raise ToolError(f"Player '{player_id}' not found.")
                flush = await finish(roll, conn=conn)
        except StaleSkillOperation as error:
            raise ToolError(str(error)) from error
    return json.dumps(await flush())


async def _finish_social(
    session,
    player_id,
    npc_id,
    skill,
    base_dc,
    roll,
    *,
    session_id: str,
    binding: zhael_foretold_words.Binding | None,
    queries,
    content,
    mutations,
    conditions_mutations,
    db_mod,
    conn=None,
    scope=None,
):
    current = await resolve_disposition(
        npc_id, player_id, conn=conn, for_update=conn is not None, queries_mod=queries, content_mod=content
    )
    try:
        outcome = social_resolution.resolve_social_check(
            disposition=current,
            skill=skill,
            roll_total=roll.total,
            base_dc=base_dc,
            exact_dc=binding["dc"] if binding is not None else None,
        )
    except ValueError as error:
        raise ToolError(str(error)) from error

    shift = outcome.new_disposition != current
    consumed_state = None
    if shift or roll.consumed_conditions:
        async with (
            db_mod.transaction()
            if conn is None and shift and roll.consumed_conditions
            else nullcontext(conn) as write_conn
        ):
            if scope is None:
                session.validate_acting_player(player_id)
            else:
                scope.validate(session)
            # Match held settlement's player-before-disposition lock order.
            if roll.consumed_conditions:
                consumed_state = await consume_beneficial_conditions(
                    player_id,
                    roll.consumed_conditions,
                    conditions_mutations,
                    conn=write_conn,
                    combat_state=session.combat_state,
                    db_mod=db_mod,
                )
            if shift:
                await mutations.set_npc_disposition(
                    npc_id,
                    player_id,
                    outcome.new_disposition,
                    f"social_check: {skill}",
                    **({"conn": write_conn} if write_conn is not None else {}),
                )

    if binding is not None:
        assert conn is not None
        await zhael_foretold_words.clear(conn, player_id, npc_id, session_id, binding)

    async def flush():
        if consumed_state is not None:
            session.combat_state = consumed_state
        verdict = "success" if outcome.success else "failure"
        session.record_event(f"Social check ({skill} vs {npc_id}): {verdict}")
        await publish_game_event(
            session.room,
            E.DICE_ROLL,
            {
                "roll_type": "social_check",
                "skill": skill,
                "roll": roll.roll,
                "total": roll.total,
                "success": outcome.success,
                "dramatic": outcome.dramatic,
                "context": outcome.context,
            },
            event_bus=session.event_bus,
        )
        if shift:
            await publish_game_event(
                session.room,
                E.DISPOSITION_CHANGED,
                {"npc_id": npc_id, "previous": current, "new": outcome.new_disposition},
                event_bus=session.event_bus,
            )
        return {
            "outcome": verdict,
            "npc_id": npc_id,
            "skill": skill,
            "roll": roll.roll,
            "total": roll.total,
            "dc": outcome.dc,
            "margin": outcome.margin,
            "dramatic": outcome.dramatic,
            "context": outcome.context,
            "narrative_cue": outcome.narrative_cue,
            "disposition_shift": outcome.disposition_shift,
            "previous_disposition": current,
            "new_disposition": outcome.new_disposition,
            **(zhael_foretold_words.CLAUSE_RECEIPT if binding is not None else {}),
            **({"gift_name": roll.gift_name} if roll.gift_name else {}),
        }

    return flush
