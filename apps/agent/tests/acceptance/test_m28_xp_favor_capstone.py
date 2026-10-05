"""The L5 fork cue has focused progression coverage; this capstone reaches the L10 auto-grant boundary."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from _retired_tools import RETIRED_TOOL_REPLACEMENTS
from acceptance.seeds import seed_player
from agent_tool_profiles import AGENT_TOOL_LISTS
from sample_fixtures import make_context, make_mock_room, published_payloads

import db
import db_mutations
import db_queries
import event_types as E
import milestones
import quest_tools
from combat_end import _end_combat_db
from combat_events import EventSink
from exploration_agent import EXPLORATION_TOOLS
from llm_config import MAX_STRICT_TOOLS
from session_data import CombatParticipant, CombatState, SessionData

# The ONLY authored stage declaring both rewards: greyvale_anomaly stage index 4
# ("stage_5_return") pays xp 200 + favor 5. Firing it means seeding current_stage=4 and
# asking for stage 5 — len(stages) is the completion transition.
_QUEST_ID = "greyvale_anomaly"
_FINAL_STAGE = 5

# A 2-seat party turns the authored 200 into an exact boundary landing:
#   party_reward_multiplier(2) = 1.5 -> int(200 * 1.5 / 2) = 150 each
#   3300 + 150 == 3450 == XP_FOR_LEVEL[10]
# The share is written out rather than derived from party_reward_multiplier ON PURPOSE: deriving
# it would make this net pass through a change to the grouping curve, which is exactly the
# regression it exists to catch (tests/test_quest_tools.py derives, for the opposite reason).
# The authored side of the coupling is pinned by test_the_authored_stage_still_declares_the_seed
# below, so a content rebalance reds with "content changed", not with mystery arithmetic.
# The second seat is seeded clear of any boundary so it cannot add an unplanned grant.
_STAGE_XP = 200
_QUEST_XP_SHARE = 150
_L10_XP = 3450
_PRIMARY_SEED_XP = _L10_XP - _QUEST_XP_SHARE
_SECOND_SEED_XP = 3000

# favor `max` must sit well above level + 5, or _award_divine_favor_core's
# min(current + amount, max) clamp silently absorbs the grant and proves nothing.
_FAVOR_START = 10
_FAVOR_AWARD = 5
_PATRON = "kaelen"


async def _seed_hero(pool, player_id: str, *, level: int, xp: int, patron: str | None) -> None:
    """seed_player + level/xp at a chosen point, and optionally a patron to receive favor.

    seed_player defaults to level 2 with no `xp` and no `divine_favor` key; the Resolves read
    both, and db_mutations_divine.update_divine_favor writes through jsonb_set, so the
    divine_favor block must already exist for a grant to land.
    """
    await seed_player(pool, player_id=player_id, class_="warrior")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{level}', $2::jsonb), '{xp}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps(level),
        json.dumps(xp),
    )
    if patron is not None:
        await pool.execute(
            "UPDATE players SET data = jsonb_set(data, '{divine_favor}', $2::jsonb, true) WHERE player_id = $1",
            player_id,
            json.dumps({"patron": patron, "level": _FAVOR_START, "max": 100, "last_whisper_level": _FAVOR_START}),
        )


async def _cleanup(pool, *player_ids: str) -> None:
    """Drop the parent row and let the FKs take the children.

    Every per-player table these stages write — player_quests, the world_effects' npc_dispositions
    and player_reputation, and combat loot's player_inventory — carries ON DELETE CASCADE on
    players.player_id (migration 021). Deleting the children by hand would be both redundant and a
    list that silently rots as new per-player tables appear.
    """
    for pid in player_ids:
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


# --- 1. No agent registers an award tool (the headline M28 "done") -----------------------


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_no_agent_registers_award_tools(name: str, tools: list) -> None:
    retired = {"award_xp", "award_divine_favor"}
    assert all(RETIRED_TOOL_REPLACEMENTS[tool] is None for tool in retired)
    leaked = retired & {t.__name__ for t in tools}
    assert not leaked, f"{name} still registers removed award tool(s): {sorted(leaked)}"


# --- 2. The tool-ceiling win holds ------------------------------------------------------


def test_exploration_keeps_five_free_slots() -> None:
    assert len(EXPLORATION_TOOLS) == 15
    assert len(EXPLORATION_TOOLS) <= MAX_STRICT_TOOLS - 5


# --- 2b. The authored content this net's arithmetic is seeded from ----------------------


async def test_the_authored_stage_still_declares_the_seed(reset_db_pool: str) -> None:
    """Anchor the hand-derived boundary seed to authored content so rebalance failures explain the changed reward."""
    import db_content_queries

    quest = await db_content_queries.get_quest(_QUEST_ID)
    assert quest is not None, f"{_QUEST_ID} is no longer authored content"
    stages = quest["stages"]
    assert len(stages) == _FINAL_STAGE, f"stage count moved: {len(stages)} != {_FINAL_STAGE}"
    on_complete = stages[_FINAL_STAGE - 1]["on_complete"]
    assert (on_complete.get("xp"), on_complete.get("favor")) == (_STAGE_XP, _FAVOR_AWARD), (
        "greyvale_anomaly's final stage was rebalanced; re-derive _QUEST_XP_SHARE and the seeds"
    )
    assert int(_STAGE_XP * 1.5 / 2) == _QUEST_XP_SHARE, "the hand-written share no longer matches the seed"


# --- 3. Quest completion pays the party: XP split, favor undivided, boundary grant --------


async def test_quest_completion_splits_xp_and_pays_favor_undivided(reset_db_pool: str) -> None:
    """Choose a seed that lands authored XP exactly on the level boundary without mocking the catalog."""
    pool = await db.get_pool()
    primary, second = "cap_m28_primary", "cap_m28_second"
    try:
        await _seed_hero(pool, primary, level=9, xp=_PRIMARY_SEED_XP, patron=_PATRON)
        await _seed_hero(pool, second, level=9, xp=_SECOND_SEED_XP, patron=_PATRON)
        await milestones.load_milestones()
        await db_mutations.set_player_quest(
            primary, _QUEST_ID, {"current_stage": _FINAL_STAGE - 1, "quest_name": "The Greyvale Anomaly"}
        )

        ctx = make_context(player_id=primary, room=make_mock_room(), party_member_ids=[second])
        result = json.loads(await quest_tools._update_quest_impl(ctx, _QUEST_ID, _FINAL_STAGE))

        # XP is SHARED — split by the party multiplier, so neither seat takes the whole 200.
        primary_row = await db_queries.get_player(primary)
        second_row = await db_queries.get_player(second)
        assert primary_row is not None and second_row is not None
        assert primary_row["xp"] == _PRIMARY_SEED_XP + _QUEST_XP_SHARE == _L10_XP
        assert second_row["xp"] == _SECOND_SEED_XP + _QUEST_XP_SHARE

        # The primary crossed a milestone boundary; the auto-grant is persisted, not narrated.
        assert primary_row["level"] == 10
        assert primary_row["flags"]["extra_attack"] is True
        assert any(g["name"] == "Extra Attack" for g in result["milestone_grants"])
        # The second seat was seeded clear of a boundary, so it must NOT have levelled.
        assert second_row["level"] == 9
        assert "flags" not in second_row

        # Divine favor is PERSONAL — the full declared amount to each member, undivided.
        for row, who in ((primary_row, primary), (second_row, second)):
            assert row["divine_favor"]["level"] == _FAVOR_START + _FAVOR_AWARD, (
                f"{who} should gain the full declared favor, not a split share"
            )
    finally:
        await _cleanup(pool, primary, second)


# --- 4. Combat exit still grants XP, with no award tool in reach -------------------------


async def test_combat_victory_grants_xp_through_the_resolve(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    fighter = "cap_m28_fighter"
    try:
        await _seed_hero(pool, fighter, level=3, xp=500, patron=None)
        await milestones.load_milestones()

        enemy = CombatParticipant(
            id="cap_m28_enemy",
            name="Ruin Stalker",
            type="enemy",
            initiative=8,
            hp_current=0,
            hp_max=14,
            ac=12,
            level=3,
            xp_value=90,
            is_fallen=True,
            role="standard",
            category="humanoid",
            tier=1,
        )
        player = CombatParticipant(
            id=fighter, name="Capstone Hero", type="player", initiative=15, hp_current=18, hp_max=18, ac=14
        )
        cs = CombatState(
            combat_id="cap_m28_combat",
            participants=[player, enemy],
            initiative_order=[fighter, enemy.id],
        )

        session = SessionData(player_id=fighter, location_id="greyvale_ruins_entrance", room=None)
        sink = EventSink()
        async with db.transaction() as conn:
            end_data = await _end_combat_db(
                session, cs, "victory", mutations=db_mutations, queries=db_queries, conn=conn, sink=sink
            )

        assert end_data["xp_granted"] > 0
        row = await db_queries.get_player(fighter)
        assert row is not None and row["xp"] == 500 + end_data["xp_granted"]
        assert any(ev.event_type == E.XP_AWARDED for ev in sink.captured), (
            "the combat-exit Resolve must buffer its XP cue for post-commit release"
        )
    finally:
        await _cleanup(pool, fighter)


# --- 5. A member with no patron is skipped, not fatal ------------------------------------


async def test_a_member_without_a_patron_is_skipped_not_fatal(reset_db_pool: str) -> None:
    """Favor needs a patron; missing relationships must not abort the party reward."""
    pool = await db.get_pool()
    primary, godless = "cap_m28_faithful", "cap_m28_godless"
    try:
        await _seed_hero(pool, primary, level=9, xp=_PRIMARY_SEED_XP, patron=_PATRON)
        await _seed_hero(pool, godless, level=9, xp=_SECOND_SEED_XP, patron=None)
        await milestones.load_milestones()
        await db_mutations.set_player_quest(
            primary, _QUEST_ID, {"current_stage": _FINAL_STAGE - 1, "quest_name": "The Greyvale Anomaly"}
        )

        ctx = make_context(player_id=primary, room=make_mock_room(), party_member_ids=[godless])
        await quest_tools._update_quest_impl(ctx, _QUEST_ID, _FINAL_STAGE)

        faithful_row = await db_queries.get_player(primary)
        godless_row = await db_queries.get_player(godless)
        assert faithful_row is not None and godless_row is not None
        assert faithful_row["divine_favor"]["level"] == _FAVOR_START + _FAVOR_AWARD
        assert "divine_favor" not in godless_row
        # The stage still completed for both — XP is not gated on having a patron.
        assert godless_row["xp"] == _SECOND_SEED_XP + _QUEST_XP_SHARE
    finally:
        await _cleanup(pool, primary, godless)


# --- 6. Nothing reaches the client before the transaction commits ------------------------


async def test_a_rolled_back_stage_grants_and_publishes_nothing(reset_db_pool: str) -> None:
    """Inject failure after rewards run. Real rollback must undo their writes and drop unflushed events."""
    pool = await db.get_pool()
    primary = "cap_m28_rollback"
    try:
        await _seed_hero(pool, primary, level=9, xp=_PRIMARY_SEED_XP, patron=_PATRON)
        await milestones.load_milestones()
        await db_mutations.set_player_quest(
            primary, _QUEST_ID, {"current_stage": _FINAL_STAGE - 1, "quest_name": "The Greyvale Anomaly"}
        )

        ctx = make_context(player_id=primary, room=make_mock_room())
        with patch.object(db_mutations, "set_player_quest", AsyncMock(side_effect=RuntimeError("stage write failed"))):
            with pytest.raises(RuntimeError, match="stage write failed"):
                await quest_tools._update_quest_impl(ctx, _QUEST_ID, _FINAL_STAGE)

        row = await db_queries.get_player(primary)
        assert row is not None
        assert row["xp"] == _PRIMARY_SEED_XP, "a rolled-back stage must leave no XP behind"
        assert row["divine_favor"]["level"] == _FAVOR_START, "a rolled-back stage must leave no favor behind"
        assert published_payloads(ctx.userdata.room) == [], (
            "no reward cue may reach the client for a stage that never committed"
        )
    finally:
        await _cleanup(pool, primary)
