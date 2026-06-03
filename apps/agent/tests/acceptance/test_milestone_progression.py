"""Real-DB E2E capstone for M4 (Resolve consolidation + select).

Proves the M4 milestone model composes end-to-end on real infra (auto-marked
`acceptance` by tests/acceptance/conftest.py), across both surfaces:

- **message_event** (Python agent path): against a real Postgres testcontainer
  seeded from content/archetype_milestones.json, `load_milestones()` loads the
  catalog and the M4 Resolve runs against the real DB — `award_xp` (and
  `update_quest`, routed through the same `_award_xp_core`) applies the L10/15/20
  auto-grants at the single leveling chokepoint and surfaces the L5 specialization
  fork as a SPECIALIZATION_CHOICE event on level-up WITHOUT persisting; the `select`
  verb persists the chosen specialization immutably and rejects a second/invalid
  resolution. resolve_milestone no longer exists. The warrior tiers cover every
  kind: L5 specialization_fork (not patron-deferred), L10 auto_grant with a combat
  flag (extra_attack), L15 auto_grant that is narrative-only (flag=null).
- **http_websocket** (TS server path): the Bun server boots bound to the SAME
  seeded testcontainer; its startup Promise.all runs loadMilestones() over all
  milestone rows — a served response proves the TS loader parsed every row without
  failing boot (a row that crashes parseMilestoneRow crashes boot).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from acceptance._server import start_server
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import choice_tools
import db
import db_mutations
import db_queries
import event_types as E
import milestones
import progression_tools
import quest_tools


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_warrior(pool, player_id: str, level: int, xp: int) -> None:
    """seed_player + set players.data.level AND xp to a point just below a milestone.

    seed_player defaults to level 2 and sets no xp key; the M4 Resolve reads both
    player['level'] and player['xp'], so jsonb_set both (create_missing creates xp).
    """
    await seed_player(pool, player_id=player_id, class_="warrior")
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{level}', $2::jsonb), '{xp}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps(level),
        json.dumps(xp),
    )


# --- message_event surface (M4 Resolve path) ---


@pytest.mark.asyncio
async def test_award_xp_l5_surfaces_fork_without_persisting(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_l5_present"
    await _seed_warrior(pool, pid, level=4, xp=750)
    await milestones.load_milestones()
    assert milestones.is_loaded()

    room = make_mock_room()
    ctx = make_context(player_id=pid, room=room)
    raw = await progression_tools._award_xp_impl(ctx, 300, "crossed into L5")
    result = json.loads(raw)

    # The level-up surfaces the L5 fork as a pending choice (cue + HUD event), no persist.
    assert result["specialization_fork"] is True
    choice_evt = next(
        (
            evt
            for c in room.local_participant.publish_data.call_args_list
            if (evt := json.loads(c[0][0]))["type"] == E.SPECIALIZATION_CHOICE
        ),
        None,
    )
    assert choice_evt is not None
    assert choice_evt["milestone_id"] == "warrior_identity"
    assert {o["id"] for o in choice_evt["options"]} == {"warrior_battle_master", "warrior_berserker"}

    player = await db_queries.get_player(pid)
    assert player is not None
    assert player.get("specialization") is None


@pytest.mark.asyncio
async def test_select_persists_specialization_immutably(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_select"
    await _seed_warrior(pool, pid, level=5, xp=1050)
    await milestones.load_milestones()
    ctx = make_context(player_id=pid, room=make_mock_room())

    raw = await choice_tools._select_impl(ctx, "warrior_identity", "warrior_battle_master")
    assert json.loads(raw)["chosen"] == "warrior_battle_master"

    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["specialization"] == "warrior_battle_master"

    # A second resolution (even a different valid option) is rejected — the choice is permanent.
    with pytest.raises(ToolError):
        await choice_tools._select_impl(ctx, "warrior_identity", "warrior_berserker")
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["specialization"] == "warrior_battle_master"


@pytest.mark.asyncio
async def test_select_invalid_option_rejected_without_mutating(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_select_invalid"
    await _seed_warrior(pool, pid, level=5, xp=1050)
    await milestones.load_milestones()
    ctx = make_context(player_id=pid, room=make_mock_room())

    with pytest.raises(ToolError):
        await choice_tools._select_impl(ctx, "warrior_identity", "warrior_nonsense")

    player = await db_queries.get_player(pid)
    assert player is not None
    assert player.get("specialization") is None


@pytest.mark.asyncio
async def test_award_xp_l10_auto_grant_sets_extra_attack_flag(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_l10"
    await _seed_warrior(pool, pid, level=9, xp=2900)
    await milestones.load_milestones()

    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await progression_tools._award_xp_impl(ctx, 550, "crossed into L10")
    result = json.loads(raw)
    assert any(g["name"] == "Extra Attack" for g in result["milestone_grants"])

    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["flags"]["extra_attack"] is True


@pytest.mark.asyncio
async def test_award_xp_l15_narrative_grant_writes_no_flag(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_l15"
    await _seed_warrior(pool, pid, level=14, xp=6000)
    await milestones.load_milestones()

    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await progression_tools._award_xp_impl(ctx, 750, "crossed into L15")
    result = json.loads(raw)
    assert any(g["name"] == "Indomitable" for g in result["milestone_grants"])

    # Narrative-only auto-grant (flag=null) writes no combat flag.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert "flags" not in player


@pytest.mark.asyncio
async def test_update_quest_crossing_milestone_applies_grant(reset_db_pool: str) -> None:
    # The M4 dedup proof: a quest reward crossing L10 applies the same auto-grant as
    # award_xp, because update_quest routes through _award_xp_core. The quest catalog
    # is mocked (real quests cap at 200 xp); the player/quest/grant writes are real.
    pool = await db.get_pool()
    pid = "cap_quest_l10"
    await _seed_warrior(pool, pid, level=9, xp=2900)
    await milestones.load_milestones()
    await db_mutations.set_player_quest(pid, "q1", {"current_stage": 0, "quest_name": "Cap Quest"})

    content = MagicMock()
    content.get_quest = AsyncMock(
        return_value={
            "name": "Cap Quest",
            "stages": [
                {"id": 0, "objective": "begin", "on_complete": {"xp": 550}},
                {"id": 1, "objective": "next", "on_complete": {}},
            ],
        }
    )
    content.get_item = AsyncMock(return_value=None)
    ctx = make_context(player_id=pid, room=make_mock_room())
    raw = await quest_tools._update_quest_impl(ctx, "q1", 1, content=content)
    result = json.loads(raw if isinstance(raw, str) else raw[1])
    assert any(g["name"] == "Extra Attack" for g in result["milestone_grants"])

    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["flags"]["extra_attack"] is True


# --- http_websocket surface (TS server milestone-load path) ---


def test_server_boots_with_milestones_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup
    # Promise.all runs loadMilestones() against the seeded testcontainer, so a served
    # response proves all milestone rows parsed without failing boot — a malformed/
    # missing row would crash parseMilestoneRow first.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500
