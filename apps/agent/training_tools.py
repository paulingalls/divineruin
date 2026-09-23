"""Training-cycle agent tools (M1.5).

Errors raise LiveKit `ToolError` (ADR 0002) — the framework surfaces the message
to the LLM. `_*_impl` helpers expose `db_mod=`, `db_training_mod=`, `db_content_mod=`,
`rules_mod=`, `now_fn=` keyword arguments — TEST-ONLY injection seams; production
callers use the `@function_tool` wrappers. Do not call the `_impl` directly from
production code.
"""

import json
import logging
from datetime import UTC, datetime
from typing import get_args

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import archetypes
import character_spells
import db
import db_content_queries
import db_queries
import db_training
import leveling
import spell_knowledge
import spells
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from session_data import SessionData
from tool_support import _validate_id
from training_rules import TrainingState, resolve_midpoint_decision, start_training_cycle

logger = logging.getLogger("divineruin.tools")

_AWAITING_DECISION_STATE: TrainingState = "awaiting_decision"


def _player_chassis(archetype: str) -> archetypes.Chassis:
    """ADR 0002: a player row carrying no known archetype surfaces to the LLM as a
    ToolError, the way the TS route answers the same row with a 400."""
    try:
        return archetypes.get_archetype_chassis(archetype)
    except ValueError as exc:
        raise ToolError(f"Unknown archetype: {archetype!r}") from exc


async def _query_training_programs_impl(
    context: RunContext[SessionData],
    *,
    db_content_mod=db_content_queries,
    queries_mod=db_queries,
    character_spells_mod=character_spells,
    spells_mod=spells,
    leveling_mod=leveling,
    db_training_mod=db_training,
) -> str:
    logger.info("query_training_programs called")
    player_id = context.userdata.acting_player_id
    player = await queries_mod.get_player(player_id)
    if player is None:
        raise ToolError(f"Unknown player: {player_id}")

    archetype = player.get("class", "")
    level = player.get("level", 1)
    known_spell_ids = {row["spell_id"] for row in await character_spells_mod.get_known(player_id)}
    learning_progress = await character_spells_mod.list_learning_progress(player_id)
    programs = await db_content_mod.list_training_programs()
    scoped_programs = []
    chassis = None
    for program in programs:
        activity_type = program["training_activity_type"]
        if not activity_type.startswith("spell_"):
            scoped_programs.append(program)
            continue

        if not archetype:
            scoped_programs.append({**program, "studiable_spell_ids": []})
            continue
        if chassis is None:
            chassis = _player_chassis(archetype)
        tier = activity_type.removeprefix("spell_")
        studiable_spell_ids = []
        # spells.SpellSource is the catalog's closed source vocabulary (the loader
        # fail-loud validates against it): enumerating it here rather than a literal
        # triple keeps this list equal to what the start wall accepts when a source
        # is added.
        for source in get_args(spells_mod.SpellSource):
            for spell in spells_mod.get_spells_by_source(source):
                if spell.spell_tier != tier:
                    continue
                try:
                    spell_knowledge.validate_spell_source(chassis.magic_source, spell.source)
                except ValueError:
                    continue
                if not leveling_mod.is_spell_tier_unlocked(archetype, tier, level):
                    continue
                if spell.id not in known_spell_ids:
                    studiable_spell_ids.append(spell.id)
        scoped_programs.append({**program, "studiable_spell_ids": sorted(studiable_spell_ids)})

    active_training = await db_training_mod.get_player_active_training_activities(player_id)
    return json.dumps(
        {
            "programs": scoped_programs,
            "spell_learning_progress": learning_progress,
            "active_training": [
                {
                    "id": row["id"],
                    "activity_type": row["activity_type"],
                    "state": row["state"],
                    "program_id": row["data"].get("program_id"),
                }
                for row in active_training
            ],
        }
    )


async def _initiate_training_cycle_impl(
    context: RunContext[SessionData],
    program_id: str,
    *,
    spell_id: str | None = None,
    db_mod=db,
    db_training_mod=db_training,
    db_content_mod=db_content_queries,
    queries_mod=db_queries,
    spells_mod=spells,
    character_spells_mod=character_spells,
    leveling_mod=leveling,
    rules_mod=None,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(program_id, "program_id")
    session: SessionData = context.userdata
    player_id = session.acting_player_id
    logger.info("initiate_training_cycle called: player_id=%s program_id=%s", player_id, program_id)

    program = await db_content_mod.get_training_program(program_id)
    if program is None:
        raise ToolError(f"Unknown training program: {program_id}")

    activity_type = program["training_activity_type"]
    is_spell_program = activity_type.startswith("spell_")
    if not is_spell_program:
        if spell_id is not None:
            raise ToolError(f"Training program {program_id} forbids spell_id.")
    else:
        if not spell_id:
            raise ToolError(f"Training program {program_id} requires spell_id.")
        _validate_id(spell_id, "spell_id")
        try:
            spell = spells_mod.get_spell(spell_id)
        except ValueError as exc:
            raise ToolError(f"Unknown spell: {spell_id}") from exc
        if activity_type != f"spell_{spell.spell_tier}":
            raise ToolError(
                f"Training program {program_id} is for {activity_type.removeprefix('spell_')} tier spells, "
                f"not {spell.spell_tier}."
            )

        player = await queries_mod.get_player(player_id)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")
        archetype = player.get("class", "")
        chassis = _player_chassis(archetype)
        try:
            spell_knowledge.validate_spell_source(chassis.magic_source, spell.source)
        except ValueError as exc:
            raise ToolError(f"{archetype} cannot study {spell_id}: {exc}.") from exc

        level = player.get("level", 1)
        if not leveling_mod.is_spell_tier_unlocked(archetype, spell.spell_tier, level):
            floor = leveling_mod.min_level_for_tier(archetype, spell.spell_tier)
            if floor is None:
                raise ToolError(f"Cannot study {spell_id}: {spell.spell_tier} spells are not available to {archetype}.")
            raise ToolError(
                f"Cannot study {spell_id}: {spell.spell_tier} spells unlock at level {floor} for "
                f"{archetype}, character is level {level}."
            )

        known = await character_spells_mod.get_known(player_id)
        if any(row["spell_id"] == spell_id for row in known):
            raise ToolError(f"Player already knows {spell_id}.")

    now = (now_fn or _default_now)()
    start_fn = rules_mod or start_training_cycle
    try:
        cycle = start_fn(activity_type, now)
    except ValueError as e:
        raise ToolError(str(e)) from e

    async with db_mod.transaction() as conn:
        existing_rows = await db_training_mod.get_player_active_training_activities(player_id, conn=conn)
        if existing_rows:
            raise ToolError(
                "A training cycle is already in progress. You cannot start another training cycle or switch programs "
                "until it completes. Tell the player this limit and offer to check their current cycle."
            )

        data = {
            "program_id": program["id"],
            "program_name": program["name"],
            "first_half_seconds": cycle.first_half_seconds,
            "stat": program.get("stat"),
            "skill": program.get("skill"),
            "dc": program.get("dc"),
            "mentor_id": program.get("mentor_id"),
        }
        if is_spell_program:
            data["spell_id"] = spell_id
        session.validate_acting_player(player_id)
        activity_id = await db_training_mod.create_training_activity(
            player_id=player_id,
            activity_type=activity_type,
            state=cycle.state,
            data=data,
            transition_at=cycle.decision_at,
            conn=conn,
        )

    return json.dumps(
        {
            "activity_id": activity_id,
            "state": cycle.state,
            "first_half_seconds": cycle.first_half_seconds,
            "decision_at": cycle.decision_at.isoformat(),
            "program_name": program["name"],
        }
    )


async def _resolve_training_midpoint_impl(
    context: RunContext[SessionData],
    training_id: str,
    decision_id: str,
    *,
    db_mod=db,
    db_training_mod=db_training,
    rules_mod=None,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(training_id, "training_id")
    session: SessionData = context.userdata
    player_id = session.acting_player_id
    logger.info(
        "resolve_training_midpoint called: player_id=%s training_id=%s decision_id=%s",
        player_id,
        training_id,
        decision_id,
    )

    async with db_mod.transaction() as conn:
        row = await db_training_mod.get_training_activity(training_id, conn=conn, for_update=True)
        if row is None:
            raise ToolError(f"Unknown training: {training_id}")
        if row["player_id"] != player_id:
            raise ToolError(f"Training {training_id} does not belong to this player.")
        if row["state"] != _AWAITING_DECISION_STATE:
            raise ToolError(f"Training {training_id} is in state '{row['state']}', not '{_AWAITING_DECISION_STATE}'.")

        now = (now_fn or _default_now)()
        resolve_fn = rules_mod or resolve_midpoint_decision
        try:
            result = resolve_fn(row["activity_type"], decision_id, now)
        except ValueError as e:
            raise ToolError(str(e)) from e

        data_updates = {
            "decision_id": decision_id,
            "second_half_seconds": result.second_half_seconds,
            "micro_bonus": result.micro_bonus,
        }
        session.validate_acting_player(player_id)
        await db_training_mod.update_training_activity(
            training_id,
            state=result.state,
            data_updates=data_updates,
            transition_at=result.completes_at,
            conn=conn,
        )

    await publish_action_sound(session, ACTION_SOUND_EXPORTS["ACTION_RESOLVE_TRAINING_MIDPOINT"])
    hours_left = (result.second_half_seconds + 30 * 60) // 3600
    return json.dumps(
        {
            "activity_id": training_id,
            "state": result.state,
            "second_half_seconds": result.second_half_seconds,
            "completes_at": result.completes_at.isoformat(),
            "decision_id": decision_id,
            "narration_cue": f"Training resumes into its second half, with about {hours_left} hours left.",
        }
    )


def _default_now() -> datetime:
    return datetime.now(UTC)
