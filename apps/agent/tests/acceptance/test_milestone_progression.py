"""Real-DB E2E capstone for M2.3 Specialization & Milestone Progression.

Proves the five M2.3 stories compose end-to-end on real infra (auto-marked
`acceptance` by tests/acceptance/conftest.py), across both surfaces:

- **message_event** (Python agent path): against a real Postgres testcontainer
  seeded from content/archetype_milestones.json, `load_milestones()` (story-002)
  loads the catalog, and `resolve_milestone` (story-004) drives the full milestone
  ladder against the real DB — the L5 Identity fork presents two paths without
  persisting (story-001 content), a chosen specialization persists immutably to
  players.data and a second resolution is rejected, an invalid choice mutates
  nothing, the L10 auto-grant sets the extra_attack combat flag, and the L15
  narrative-only grant (flag=null) writes no flag. This is the DB-path proof the
  unit tests (5c52b8119e21, c871cf17fcfe) explicitly deferred here.
- **http_websocket** (TS server path): the Bun server boots bound to the SAME
  seeded testcontainer; its startup Promise.all runs loadMilestones() (story-003)
  over all 72 milestone rows — a served response proves the TS loader parsed every
  row without failing boot, closing story-003's deferred live-boot E2E and the
  cross-language parity Risk (a row that crashes parseMilestoneRow crashes boot).

Mirrors the M2.2 ability capstone (test_story_005_m22_ability_capstone.py):
warrior is the matrix archetype because its four tiers cover every milestone kind
— L5 specialization_fork (not patron-deferred), L10 auto_grant with a combat flag,
L15 auto_grant that is narrative-only (flag=null).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock

import httpx
import pytest
from acceptance._server import start_server
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import db
import db_queries
import event_types as E
import milestone_tools
import milestones


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_warrior_at_level(pool, player_id: str, level: int) -> None:
    """seed_player + bump players.data.level to the milestone level.

    seed_player defaults to level 2; resolve_milestone derives the milestone from
    player['level'], so jsonb_set the top-level '{level}' key to the tier level.
    """
    await seed_player(pool, player_id=player_id, class_="warrior")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{level}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(level),
    )


# --- message_event surface (Python milestone-resolution path) ---


@pytest.mark.asyncio
async def test_l5_no_choice_presents_fork_without_persisting(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_present"
    await _seed_warrior_at_level(pool, pid, 5)
    await milestones.load_milestones()  # story-002 loader over the seeded testcontainer
    assert milestones.is_loaded()

    events = AsyncMock()
    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await milestone_tools._resolve_milestone_impl(ctx, None, events_mod=events)
    result = json.loads(raw)  # tool returns a JSON string

    assert result["milestone_id"] == "warrior_identity"
    assert result["requires_choice"] is True
    assert {o["id"] for o in result["options"]} == {"warrior_battle_master", "warrior_berserker"}
    # The HUD event was emitted for the fork.
    events.publish_game_event.assert_awaited_once()
    assert events.publish_game_event.call_args.args[1] == E.SPECIALIZATION_CHOICE

    # Presenting must NOT persist — specialization stays unset in the real DB.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player.get("specialization") is None


@pytest.mark.asyncio
async def test_l5_choice_persists_immutably_to_real_db(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_choose"
    await _seed_warrior_at_level(pool, pid, 5)
    await milestones.load_milestones()

    events = AsyncMock()
    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await milestone_tools._resolve_milestone_impl(ctx, "warrior_battle_master", events_mod=events)
    result = json.loads(raw)
    assert result["chosen"] == "warrior_battle_master"
    # Locking a choice in is HUD-silent — no SPECIALIZATION_CHOICE event (the fork
    # was already presented on the prior no-choice call).
    events.publish_game_event.assert_not_awaited()

    # Real DB mutation: the chosen specialization is persisted to players.data.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["specialization"] == "warrior_battle_master"


@pytest.mark.asyncio
async def test_l5_second_resolution_is_rejected(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_immutable"
    await _seed_warrior_at_level(pool, pid, 5)
    await milestones.load_milestones()
    ctx = make_context(player_id=pid, room=make_mock_room())

    # First resolution locks the choice in.
    await milestone_tools._resolve_milestone_impl(ctx, "warrior_battle_master")

    # A second resolution (even a different valid option) is rejected — the L5
    # choice is permanent (read under FOR UPDATE before the write).
    with pytest.raises(ToolError):
        await milestone_tools._resolve_milestone_impl(ctx, "warrior_berserker")

    # The original choice is unchanged in the real DB.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["specialization"] == "warrior_battle_master"


@pytest.mark.asyncio
async def test_l5_invalid_choice_rejected_without_mutating(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_invalid"
    await _seed_warrior_at_level(pool, pid, 5)
    await milestones.load_milestones()
    ctx = make_context(player_id=pid, room=make_mock_room())

    with pytest.raises(ToolError):
        await milestone_tools._resolve_milestone_impl(ctx, "warrior_nonsense")

    # No persistence — specialization stays unset.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player.get("specialization") is None


@pytest.mark.asyncio
async def test_l10_auto_grant_sets_extra_attack_flag_in_real_db(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_l10"
    await _seed_warrior_at_level(pool, pid, 10)
    await milestones.load_milestones()

    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await milestone_tools._resolve_milestone_impl(ctx, None)
    result = json.loads(raw)
    assert result["grant"]["name"] == "Extra Attack"
    assert result["flag"] == "extra_attack"
    assert result["narration_cue"]

    # Real DB mutation: the combat flag is set under players.data.flags.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["flags"]["extra_attack"] is True


@pytest.mark.asyncio
async def test_l15_narrative_only_grant_writes_no_flag(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior_l15"
    await _seed_warrior_at_level(pool, pid, 15)
    await milestones.load_milestones()

    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await milestone_tools._resolve_milestone_impl(ctx, None)
    result = json.loads(raw)
    # Narrative-only auto-grant: flag is null, only the narration cue is returned.
    assert result["grant"]["name"] == "Indomitable"
    assert result["flag"] is None
    assert result["narration_cue"]

    # No combat flag was written — the player gained no flags key at all.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert "flags" not in player


# --- http_websocket surface (TS server milestone-load path) ---


def test_server_boots_with_milestones_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup
    # Promise.all runs loadMilestones() (story-003) against the seeded testcontainer,
    # so a served response proves all 72 milestone rows parsed without failing boot
    # — a malformed/missing row would crash parseMilestoneRow first.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500
