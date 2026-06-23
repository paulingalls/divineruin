"""Capstone: M4.6c Gathering & Resource Discovery end-to-end against a real Postgres testcontainer.

Stories 001-003 shipped gathering in slices: the pure resolver (001), the data layer —
resource_table content + the gathering_nodes table/seed (002) — and the check(mode='gather')
tool + live node consumer (003). This capstone proves they COMPOSE on one migrated+seeded
testcontainer (auto-marked `acceptance`), driving the REAL gather pipeline against real DB writes:

- AC1: an ambient forage at a wilderness location (resource_table, no fixed node) grants the
  harvested materials into player_inventory and emits a gathering_check DICE_ROLL for the HUD.
- AC2: a rich find at a location with a fixed node marks the node discovered + depletes its
  quantity in gathering_nodes and grants the node's resource into player_inventory.
- AC3 / E2E: node depletion is enforced across gathers — a node drained to 0 is no longer
  forageable, so a follow-up gather there (no resource_table) raises "Nothing to forage here.".

Determinism: the d20 gather check is forced via an injected rng (_FixedRng) — 20 → rich_find.
Isolation: gathering nodes are GLOBAL world state (unlike per-player travel_state), so node tests
self-provision a unique node at greyvale_ruins_inner (a seeded dungeon with no seeded node / no
resource_table) and delete it in finally; inventory state is per-player → distinct player_ids.
"""

from __future__ import annotations

import json
import random

import pytest
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import db
import db_queries
import event_types as E
import gathering_tools

# Ambient stage: wilderness with a resource_table and NO fixed node (story-002 content).
_AMBIENT = "greyvale_south_road"
# Clean node stage: a seeded greyvale dungeon with no seeded node and no resource_table.
_NODE_STAGE = "greyvale_ruins_inner"


class _FixedRng(random.Random):
    """Force the d20 gather check to a fixed value (dice.roll uses randint(1, n))."""

    def __init__(self, value: int):
        super().__init__()
        self._value = value

    def randint(self, a: int, b: int) -> int:
        return self._value


def _published(room) -> list[dict]:
    return [json.loads(call[0][0]) for call in room.local_participant.publish_data.call_args_list]


async def _set_skill_tiers(pool, player_id: str, tiers: dict) -> None:
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{skill_tiers}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(tiers),
    )


async def _insert_node(pool, node_id: str, *, location_id: str, resource_type: str, quantity: int) -> None:
    data = {
        "location_id": location_id,
        "node_type": "salvage_site",  # no gather-skill home → selected as the fallback node
        "resource_type": resource_type,
        "quantity": quantity,
        "discovered": False,
        "respawn_days": 0,
    }
    await pool.execute("INSERT INTO gathering_nodes (id, data) VALUES ($1, $2)", node_id, json.dumps(data))


async def _node_data(pool, node_id: str) -> dict:
    row = await pool.fetchrow("SELECT data FROM gathering_nodes WHERE id = $1", node_id)
    return json.loads(row["data"])


async def test_m46c_ambient_forage_grants_materials_and_emits_dice_roll(reset_db_pool: str) -> None:
    """AC1: an ambient gather grants resource_table materials to inventory + emits the HUD roll."""
    pool = await db.get_pool()
    player_id = "cap_m46c_ambient"
    await seed_player(pool, player_id=player_id, location_id=_AMBIENT)
    await _set_skill_tiers(pool, player_id, {"survival": "expert"})

    ctx = make_context(player_id, location_id=_AMBIENT, room=make_mock_room())
    result = json.loads(await gathering_tools._check_gather_impl(ctx, "", rng=_FixedRng(20)))

    assert result["outcome"] == "success"
    assert result["node_revealed"] is None  # no fixed node at the ambient stage
    assert result["materials"]  # a passing forage yields material

    # Each granted material id is in player_inventory at the harvested count.
    counts: dict[str, int] = {}
    for mid in result["materials"]:
        counts[mid] = counts.get(mid, 0) + 1
    for mid, qty in counts.items():
        item = await db_queries.get_inventory_item(player_id, mid, conn=pool)
        assert item is not None and item["quantity"] == qty

    dice = [e for e in _published(ctx.userdata.room) if e.get("type") == E.DICE_ROLL]
    assert dice and dice[0]["roll_type"] == "gathering_check"


async def test_m46c_rich_find_discovers_and_depletes_node(reset_db_pool: str) -> None:
    """AC2: a rich find reveals + depletes a fixed node and grants its resource to inventory."""
    pool = await db.get_pool()
    player_id = "cap_m46c_node"
    node_id = "cap_m46c_node_salvage"
    await seed_player(pool, player_id=player_id, location_id=_NODE_STAGE)
    await _set_skill_tiers(pool, player_id, {"survival": "expert"})
    await _insert_node(pool, node_id, location_id=_NODE_STAGE, resource_type="iron_ore", quantity=2)
    try:
        ctx = make_context(player_id, location_id=_NODE_STAGE, room=make_mock_room())
        result = json.loads(await gathering_tools._check_gather_impl(ctx, "", rng=_FixedRng(20)))

        assert result["discovery"] is True
        assert result["node_revealed"] == node_id

        node = await _node_data(pool, node_id)
        assert node["discovered"] is True
        assert node["quantity"] == 1  # 2 - 1 depleted by the gather

        item = await db_queries.get_inventory_item(player_id, "iron_ore", conn=pool)
        assert item is not None and item["quantity"] == 1
    finally:
        await pool.execute("DELETE FROM gathering_nodes WHERE id = $1", node_id)


async def test_m46c_depleted_node_is_no_longer_forageable(reset_db_pool: str) -> None:
    """AC3 / E2E: a node drained to 0 is filtered out; a follow-up gather (no resource_table) raises."""
    pool = await db.get_pool()
    player_id = "cap_m46c_deplete"
    node_id = "cap_m46c_deplete_salvage"
    await seed_player(pool, player_id=player_id, location_id=_NODE_STAGE)
    await _set_skill_tiers(pool, player_id, {"survival": "expert"})
    await _insert_node(pool, node_id, location_id=_NODE_STAGE, resource_type="iron_ore", quantity=1)
    try:
        ctx = make_context(player_id, location_id=_NODE_STAGE, room=make_mock_room())
        # First rich-find gather drains the node 1 → 0.
        first = json.loads(await gathering_tools._check_gather_impl(ctx, "", rng=_FixedRng(20)))
        assert first["node_revealed"] == node_id
        assert (await _node_data(pool, node_id))["quantity"] == 0

        # No available node (quantity 0 → filtered) and the dungeon has no resource_table → no forage.
        with pytest.raises(ToolError, match="forage"):
            await gathering_tools._check_gather_impl(ctx, "", rng=_FixedRng(20))
    finally:
        await pool.execute("DELETE FROM gathering_nodes WHERE id = $1", node_id)
