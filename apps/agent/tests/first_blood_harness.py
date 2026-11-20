"""Seeded combat policies driven through real combat tools and persistence."""

import json
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import architect_balance_policy as architect_policy
from asyncpg import Connection, Pool
from livekit.agents import RunContext
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import character_spells
import combat_end
import db_mutations
import db_queries
import spell_knowledge
import spells
from combat_death_save import request_death_save
from combat_down import is_terminally_down
from combat_turn import consume_legendary_action, declare_phase, resolve_phase
from companion_profiles import get_companion_profile, select_companion_for_archetype
from companion_scaling import scale_companion_stats_to_player_level
from condition_restrictions import cannot_act
from creation_rules import build_character_data
from declaration_payloads import AbilityDecl, AttackDecl, DeclVariant, MultiattackDecl, StrikeSelection
from mode_tools import enter_mode
from progression_tools import _award_xp_core
from rules_engine import XP_FOR_LEVEL
from session_data import SessionData

SEEDS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
ARCHETYPES = ("warrior", "mage", "rogue", "cleric")
PATROL = "hollow_patrol_greyvale"
ARCHITECT_WORKS = "ashmark_architect_works"
ARCHITECT_ROUND_LIMIT = 45
ARCHITECT_DRAIN_LIMIT = 64
logger = logging.getLogger(__name__)


async def _create_player(pool: Pool, pid: str, archetype: str, location: str, level: int) -> None:
    row = build_character_data(
        "First Blood", "human", archetype, None, "", created_at=datetime(2026, 11, 1, tzinfo=UTC)
    )
    row["location_id"] = location
    await db_mutations.create_player(pid, None, row)
    if level > 1:
        async with pool.acquire() as conn, conn.transaction():
            await _award_xp_core(
                player_id=pid,
                player=row,
                amount=XP_FOR_LEVEL[level],
                reason="balance reference",
                conn=cast(Connection, conn),
                pending_events=[],
            )
        row = await db_queries.get_player(pid)
        assert row is not None
        fresh = {name: {**row[name], "current": row[name]["max"]} for name in ("hp", "stamina", "focus") if name in row}
        await pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", pid, json.dumps(fresh))


@asynccontextmanager
async def architect_party(pool: Pool, seed: int) -> AsyncIterator[tuple[RunContext[SessionData], tuple[str, ...]]]:
    player_ids = tuple(f"balance_{uuid4().hex}" for _ in ARCHETYPES)
    ctx = make_context(
        player_ids[0], location_id=ARCHITECT_WORKS, room=make_mock_room(), party_member_ids=player_ids[1:]
    )
    try:
        for archetype, pid in zip(ARCHETYPES, player_ids, strict=True):
            await _create_player(pool, pid, archetype, ARCHITECT_WORKS, 20)
        previous_random = random.getstate()
        random.seed(seed)
        try:
            with patch("dice.random.SystemRandom", return_value=random.Random(seed)):
                yield ctx, player_ids
        finally:
            random.setstate(previous_random)
    finally:
        try:
            if ctx.userdata.combat_state:
                await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id)
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = ANY($1::text[])", player_ids)


async def fight(pool, archetype, seed, encounter_id=PATROL, player_level=1, *, policy="basic"):
    assert policy in ("basic", "caster", "veilrender"), policy
    pid = f"balance_{uuid4().hex}"
    location = "ashmark_corrupted_front" if policy == "veilrender" else "greyvale_wilderness_north"
    await _create_player(pool, pid, archetype, location, player_level)
    cantrip = None
    if policy in ("caster", "veilrender") and archetype in ("mage", "cleric"):
        library = await character_spells.get_known(pid)
        known = spell_knowledge.castable_spell_ids(archetype, (s["spell_id"] for s in library))
        damage_cantrips = sorted(
            sid
            for sid in known
            if spells.get_spell(sid).spell_tier == "cantrip" and spells.get_spell(sid).combat_damage
        )
        if archetype == "mage":
            assert "arcane_bolt" in damage_cantrips, "mage has no learned arcane_bolt damage cantrip"
            cantrip = "arcane_bolt"
        elif damage_cantrips:
            cantrip = damage_cantrips[0]
    companion = select_companion_for_archetype(archetype)
    ctx = make_context(pid, room=make_mock_room(), companion_id=companion)
    ctx.userdata.companion.name = get_companion_profile(companion).name
    ctx.userdata.location_id = location
    ending = []
    original = combat_end._end_combat_db

    async def capture(session, state, outcome, **kwargs):
        player = state.get_participant(pid)
        ending.append((outcome == "victory" and not is_terminally_down(player), player.hp_current > 0))
        return await original(session, state, outcome, **kwargs)

    previous_random = random.getstate()
    rng = random.Random(seed)
    random.seed(seed)
    try:
        with (
            patch("dice.random.SystemRandom", return_value=rng),
            patch("combat_end._end_combat_db", capture),
            patch("combat_wrap._end_combat_db", capture),
        ):
            await enter_mode(ctx, "combat", encounter_id, "Balance reference")
            state = ctx.userdata.combat_state
            assert state is not None
            player = state.get_participant(pid)
            ally = state.get_participant(companion)
            assert player is not None and player.level == player_level
            expected = scale_companion_stats_to_player_level(
                get_companion_profile(companion), player.hp_max, player_level
            )
            assert ally is not None
            assert (ally.level, ally.hp_max, ally.hp_current, ally.ac, ally.attributes) == (
                expected.level,
                expected.hp,
                expected.hp,
                expected.ac,
                expected.attributes,
            )

            for _ in range(100):
                state = ctx.userdata.combat_state
                assert state is not None
                enemies = [p for p in state.participants if p.type == "enemy" and not p.is_fallen]
                target = min(enemies, key=lambda p: p.hp_current) if enemies else None
                declarations = []
                for actor in state.participants:
                    if actor.is_fallen or cannot_act(actor.conditions):
                        continue
                    victim = pid if actor.type == "enemy" else target.id if target else None
                    if victim is None:
                        continue
                    if policy == "veilrender":
                        from veilrender_harness import declaration

                        opponent = state.get_participant(victim)
                        assert opponent is not None
                        declarations.append(declaration(state, actor, opponent, cantrip if actor.id == pid else None))
                    elif actor.id == pid and cantrip:
                        declarations.append(
                            AbilityDecl(
                                kind="ability", actor_id=pid, action=cantrip, targets=[victim], argument_type=""
                            )
                        )
                    elif actor.type == "enemy" and actor.multiattack_sequence:
                        sequence = actor.multiattack_sequence
                        declarations.append(
                            MultiattackDecl(
                                kind="multiattack",
                                actor_id=actor.id,
                                action=sequence["name"],
                                strikes=[
                                    StrikeSelection(action=action, target_id=victim, held_item_id="")
                                    for action in sequence["attacks"]
                                ],
                            )
                        )
                    else:
                        declarations.append(
                            AttackDecl(
                                reshape=[],
                                kind="attack",
                                actor_id=actor.id,
                                action=actor.action_pool[0]["name"],
                                target_id=victim,
                                held_item_id="",
                                rider="",
                            )
                        )
                assert declarations, "no acting combatants before terminal wrap"
                await declare_phase(ctx, declarations)
                for _ in range(64):
                    result = await resolve_phase(ctx)
                    if isinstance(result, tuple):
                        break
                    result = json.loads(result)
                    if result.get("next", {}).get("waiting_on") is None and result["beat"] == "declaration":
                        break
                else:
                    raise AssertionError("First Blood did not drain held actions within 64 calls")
                if isinstance(result, tuple):
                    assert len(ending) == 1
                    return ending[0]
                for actor_id in result["death_saves_due"]:
                    await request_death_save(ctx, actor_id)
            raise AssertionError("First Blood exceeded 100 rounds")
    finally:
        random.setstate(previous_random)
        if ctx.userdata.combat_state:
            await db_mutations.delete_combat_state(ctx.userdata.combat_state.combat_id)
        await pool.execute("DELETE FROM players WHERE player_id=$1", pid)


async def win_counts(pool, encounter_id=PATROL, player_level=1, *, policy="basic"):
    counts, standing = {}, {}
    for archetype in ARCHETYPES:
        results = [await fight(pool, archetype, seed, encounter_id, player_level, policy=policy) for seed in SEEDS]
        assert len(results) == 20
        counts[archetype] = sum(win for win, _ in results)
        standing[archetype] = sum(win and hp for win, hp in results)
    print(f"policy={policy}; encounter={encounter_id}; level={player_level}; wins={counts}; HP>0 wins={standing}")
    return counts, standing


async def drive_architect_fight(
    ctx: RunContext[SessionData], player_ids: tuple[str, ...], seed: int
) -> tuple[str, int]:
    damage = dict.fromkeys(player_ids, 0)
    rallied = False
    last_legendary_round = 0
    for _ in range(ARCHITECT_ROUND_LIMIT):
        for _ in range(ARCHITECT_DRAIN_LIMIT):
            state = ctx.userdata.combat_state
            assert state is not None
            round_number = state.round_number
            detail = f"seed={seed}, round={round_number}, beat={state.beat}"
            players = architect_policy.participants(state, player_ids)
            owner = architect_policy.owner_of(state)
            candidates = architect_policy.targets(players)
            try:
                if (
                    state.beat in ("declaration", "narration")
                    and state.legendary_continuation is None
                    and state.open_window is None
                    and state.ally_continuation is None
                    and state.wrap_continuation is None
                    and state.inner_fire_continuation is None
                    and ctx.userdata.fate_offer is None
                    and not owner.is_fallen
                    and not cannot_act(owner.conditions)
                    and owner.legendary_actions >= 2
                    and last_legendary_round != round_number
                    and (target := architect_policy.geometry_target(state, owner, candidates)) is not None
                ):
                    result = await consume_legendary_action(ctx, owner.id, architect_policy.GEOMETRY, target.id, [])
                    last_legendary_round = round_number
                elif state.beat == "declaration" and state.legendary_continuation is None:
                    declarations: list[DeclVariant] = []
                    for actor in [*players, *(p for p in state.participants if not p.is_ally and not p.is_structure)]:
                        if actor.is_fallen or cannot_act(actor.conditions):
                            continue
                        if actor.id in damage:
                            row = await db_queries.get_player(actor.id)
                            assert row is not None, detail
                            declaration = architect_policy.player_declaration(
                                state, actor, owner, players, row, damage, rallied
                            )
                        elif actor.id == owner.id:
                            declaration = architect_policy.owner_declaration(state, owner, candidates)
                        else:
                            declaration = architect_policy.construct_declaration(state, actor, candidates)
                        declarations.append(declaration)
                    logger.debug("%s declarations: %s", detail, declarations)
                    accepted = json.loads(await declare_phase(ctx, declarations))
                    assert accepted["accepted_actors"] == [d.actor_id for d in declarations], detail
                    continue
                else:
                    result = await resolve_phase(ctx)
            except ToolError as error:
                raise AssertionError(f"{detail}: {error}") from error

            if isinstance(result, tuple):
                outcome = json.loads(result[1])["outcome"]
                assert outcome in ("victory", "defeat"), (detail, outcome)
                assert ctx.userdata.combat_state is None, detail
                assert await db_mutations.load_combat_state(state.combat_id) is None, detail
                return outcome, round_number

            ctx.userdata.event_bus.drain()
            packet = json.loads(result)
            assert ctx.userdata.fate_offer is None, detail
            for action in packet["packets"]:
                actor_id = action["actor_id"]
                if actor_id in damage:
                    damage[actor_id] += sum(
                        strike.get("damage", 0) for strike in action.get("attacks", [action])
                    ) + action.get("cast", {}).get("damage_result", {}).get("damage", 0)
                if action.get("action") == architect_policy.RALLYING_SHOUT and action.get("resolved"):
                    rallied = True
                logger.debug("%s: %s", detail, action)
            due = packet["death_saves_due"]
            assert len(due) == len(set(due)), (detail, due)
            for actor_id in due:
                try:
                    await request_death_save(ctx, actor_id)
                except ToolError as error:
                    raise AssertionError(f"{detail}: death save for {actor_id}: {error}") from error
            if packet["round"] > round_number:
                break
        else:
            raise AssertionError(f"{detail}: did not drain the round within {ARCHITECT_DRAIN_LIMIT} tool calls")
    hp = {p.archetype_id or p.name: p.hp_current for p in [*players, owner]}
    raise AssertionError(f"{detail}: exceeded {ARCHITECT_ROUND_LIMIT} rounds, remaining HP={hp}")
