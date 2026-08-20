"""Capstone: M28 XP and divine favor hold together as Resolves (story-004).

M28 shipped across stories 001-003 (all merged): combat exit grants XP party-wide
(story-001), quest completion grants XP and favor (story-002), and both `award_xp`
and `award_divine_favor` were torn out as LLM tools along with their `_impl` bodies
(story-003, exploration 16 -> 14). Rewards are now granted ONLY by deterministic
Resolves — there is no verb an LLM can call to grant one by judgement, because a
second grant path is a second rule waiting to drift from the first.

Each story was reviewed against its own diff. This capstone is the integration net
those reviews could not see (auto-marked ``acceptance`` by tests/acceptance/conftest.py):

  1. No agent's tool registry re-admits award_xp/award_divine_favor.
  2. The tool-ceiling win holds — exploration is exactly 14.
  3. A real quest completion pays the party: XP SPLIT by the party multiplier, favor
     UNDIVIDED to every member, and the primary's L10 auto-grant fires on the boundary.
  4. Combat exit still grants XP with no award tool in reach.
  5. A member with no patron is skipped, not fatal — the stage completes for the rest.
  6. Nothing reaches the client before the transaction commits.

Test 3 is the one that discriminates: 1/2 assert absence, and 5/6 would pass against a
tree that grants no favor at all. It was mutation-checked both ways before landing —
forcing ``party_reward_multiplier`` to 1.0 reds the XP split, stubbing the favor core
to ``None`` reds the favor assertions.

The L5 specialization-fork cue is deliberately NOT asserted here: M28's `done` names it,
but it is already pinned in the fast lane by test_progression_tools.py's
``test_core_l5_fork_emits_specialization_choice_event``, and this net pins the L10
auto-grant boundary instead. No production code changes — every symbol here is owned by
the merged stories.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.seeds import seed_player
from acceptance.test_m5_verb_consolidation import AGENT_TOOL_LISTS, REMOVED_PROGRESSION_TOOLS
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
# The second seat is seeded clear of any boundary so it cannot add an unplanned grant.
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
    """Children before parents, and every table the stage's world_effects touch."""
    for pid in player_ids:
        await pool.execute("DELETE FROM player_quests WHERE player_id = $1", pid)
        await pool.execute("DELETE FROM player_reputation WHERE player_id = $1", pid)
        await pool.execute("DELETE FROM npc_dispositions WHERE player_id = $1", pid)
        await pool.execute("DELETE FROM players WHERE player_id = $1", pid)


# --- 1. No agent registers an award tool (the headline M28 "done") -----------------------


@pytest.mark.parametrize("name,tools", AGENT_TOOL_LISTS)
def test_no_agent_registers_award_tools(name: str, tools: list) -> None:
    """Re-asserts the award-tool invariant under the M28 capstone's own name, so the
    milestone-exit net names it directly. This net's ASSERTION is independent of M5's
    combined-union check — a re-added award_xp/award_divine_favor fails here even if M5's own
    test ever drops REMOVED_PROGRESSION_TOOLS from its union. It DOES share M5's
    AGENT_TOOL_LISTS/REMOVED_PROGRESSION_TOOLS constants (one source of truth for the agent
    registries), so narrowing or renaming those there narrows/breaks this net too."""
    leaked = REMOVED_PROGRESSION_TOOLS & {t.__name__ for t in tools}
    assert not leaked, f"{name} still registers removed award tool(s): {sorted(leaked)}"


# --- 2. The tool-ceiling win holds ------------------------------------------------------


def test_exploration_holds_the_two_freed_slots() -> None:
    """M28's stated payoff is verb budget: dropping both award verbs took exploration 16 -> 14,
    widening the headroom under the strict-tool ceiling from 4 slots to 6. Re-adding either
    verb reds here as well as in test 1."""
    assert len(EXPLORATION_TOOLS) == 14
    assert len(EXPLORATION_TOOLS) <= MAX_STRICT_TOOLS - 6


# --- 3. Quest completion pays the party: XP split, favor undivided, boundary grant --------


async def test_quest_completion_splits_xp_and_pays_favor_undivided(reset_db_pool: str) -> None:
    """The discriminating test. One REAL authored quest completion proves the whole M28
    reward classification at once: XP is SHARED (the 200 becomes 150 each under the 2-seat
    multiplier, not 200 each and not 100 each), divine favor is PERSONAL (the full declared 5
    to every member, undivided), and the primary's crossing into L10 applies its auto-grant.

    The seed is chosen so the authored 200 lands exactly on 3450 — no mocked catalog, because
    exercising real content is most of what a capstone is for.
    """
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
        raw = await quest_tools._update_quest_impl(ctx, _QUEST_ID, _FINAL_STAGE)
        result = json.loads(raw if isinstance(raw, str) else raw[1])

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
    """The other grant path. _end_combat_db pays XP inside its own transaction and buffers the
    cue into the sink — the response no longer cues the DM to call anything, because there is
    nothing left to call."""
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
    """Favor is a relationship with a specific god, so a member who has none simply receives
    nothing. That must not abort the stage for everyone else — the grant is a reward, not a
    precondition."""
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
    """Every Resolve buffers into pending_events and releases only after the commit. Injecting
    a failure AFTER the reward passes have run (set_player_quest writes at the end of the
    transaction) must leave the database unmoved and the client told nothing — a player who
    saw "+150 XP" for a stage that never landed would be worse than one who saw nothing.

    The mock here injects a FAILURE; it does not stand in for any seam under test.
    """
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
