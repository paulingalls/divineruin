"""M5.4 capstone — durability surfaces compose end-to-end on real Postgres.

Proves, against one seeded testcontainer, that the Milestone-4 durability work
(stories 001/002/003/004/006/008/009/010/011) composes across both surfaces:

- message_event (Python agent): durability accrual across all 4 tiers, Hollow 2x
  corrosion driven by session state, the blacksmith repair tool (restore + debit),
  and the magic-item craft-tier content invariant.
- http_websocket (Bun REST): the repair price quote, proving it prices off the same
  rarity SSOT the agent uses (parity) and that the rarity tier is load-bearing.

Auto-marked `acceptance` (under tests/acceptance/); runs via
`cd apps/agent && uv run pytest -m acceptance tests/acceptance/test_durability_e2e.py`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server
from acceptance.seeds import seed_player
from sample_fixtures import make_context, make_mock_room

import combat_resolution
import db
import durability
from combat_support import _accrue_durability
from pricing_queries import get_economy_pricing
from recipe_validation import validate_magic_item_craft_tier
from repair_item import _repair_item_impl
from workspace import compute_rental_price

# grimjaw_blacksmith's daytime post (content/npcs.json schedule); default_disposition
# is `neutral`, which clears the repair tool's "refuse below Neutral" gate.
FORGE = "accord_forge"
SMITH = "grimjaw_blacksmith"

# One real catalog item per durability tier (id, item type, max hits) — content/items.json.
TIER_ITEMS: dict[str, tuple[str, str, int]] = {
    "fragile": ("club_wooden", "weapon", 3),
    "standard": ("shortsword_basic", "weapon", 10),
    "reinforced": ("chain_mail", "armor", 25),
    "masterwork": ("veil_ward_anchor_large", "tool", 50),
}


@pytest.fixture(scope="module")
def durability_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer (http_websocket surface)."""
    yield from start_server(migrated_db)


async def _seed_inventory_item(pool, player_id: str, item_id: str, current_hits: int) -> None:
    """Put a real catalog item in the player's inventory at `current_hits` (per-instance state)."""
    await pool.execute(
        "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb",
        player_id,
        item_id,
        json.dumps({"current_hits": current_hits}),
    )


async def _inventory_hits(pool, player_id: str, item_id: str) -> int:
    row = await pool.fetchrow(
        "SELECT data FROM player_inventory WHERE player_id = $1 AND item_id = $2", player_id, item_id
    )
    return json.loads(row["data"])["current_hits"]


async def _set_gold_and_crafting(pool, player_id: str, gold: int, tier: str) -> None:
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{gold}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(gold),
    )
    await pool.execute(
        "INSERT INTO skill_advancement (player_id, skill_id, tier, use_counter, narrative_moment_ready) "
        "VALUES ($1, 'crafting', $2, 0, false) "
        "ON CONFLICT (player_id, skill_id) DO UPDATE SET tier = $2",
        player_id,
        tier,
    )


# --- message_event surface (Python agent) ---


async def test_durability_accrues_across_all_four_tiers(reset_db_pool: str) -> None:
    """One base hit drops the PERSISTED current_hits by 1 on every durability tier."""
    player_id = "player_durab_tiers"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, location_id=FORGE)
    session = make_context(player_id=player_id, location_id=FORGE, room=make_mock_room()).userdata

    for tier, (item_id, item_type, full) in TIER_ITEMS.items():
        assert durability.max_hits(tier) == full  # tier table sanity
        await _seed_inventory_item(pool, player_id, item_id, current_hits=full)
        item = {"id": item_id, "type": item_type, "durability_tier": tier, "slot_info": {"current_hits": full}}
        await _accrue_durability(session, player_id, item, 1, is_hollow_zone=False)
        assert await _inventory_hits(pool, player_id, item_id) == full - 1, tier


async def test_hollow_zone_doubles_durability_loss_via_session_state(reset_db_pool: str) -> None:
    """corruption_level >= 2 makes the same base hit cost 2 durability; below it, 1.

    The 2x flows from session.corruption_level through is_hollow_zone — not a hardcoded flag.
    """
    player_id = "player_hollow"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, location_id=FORGE)
    item_id, item_type, full = TIER_ITEMS["standard"]
    session = make_context(player_id=player_id, location_id=FORGE, room=make_mock_room()).userdata

    # Hollow zone (corruption 2): 1 base hit -> 2 lost.
    session.corruption_level = 2
    is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
    assert is_hollow is True
    await _seed_inventory_item(pool, player_id, item_id, current_hits=full)
    item = {"id": item_id, "type": item_type, "durability_tier": "standard", "slot_info": {"current_hits": full}}
    await _accrue_durability(session, player_id, item, 1, is_hollow_zone=is_hollow)
    assert await _inventory_hits(pool, player_id, item_id) == full - 2

    # Calm zone (corruption 1): 1 base hit -> 1 lost.
    session.corruption_level = 1
    is_hollow = combat_resolution.is_hollow_zone(session.corruption_level)
    assert is_hollow is False
    await _seed_inventory_item(pool, player_id, item_id, current_hits=full)
    item = {"id": item_id, "type": item_type, "durability_tier": "standard", "slot_info": {"current_hits": full}}
    await _accrue_durability(session, player_id, item, 1, is_hollow_zone=is_hollow)
    assert await _inventory_hits(pool, player_id, item_id) == full - 1


async def test_blacksmith_repair_restores_durability_and_debits_gold(reset_db_pool: str) -> None:
    """The repair tool restores durability to the tier max, prices off the rarity
    SSOT, and debits gold — the full blacksmith path against the seeded DB."""
    player_id = "player_repair_msg"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, location_id=FORGE)
    await _set_gold_and_crafting(pool, player_id, gold=100, tier="trained")  # standard repair needs 'trained'
    item_id, _type, full = TIER_ITEMS["standard"]  # shortsword_basic, common rarity
    await _seed_inventory_item(pool, player_id, item_id, current_hits=2)

    ctx = make_context(player_id=player_id, location_id=FORGE, room=make_mock_room())
    result = json.loads(await _repair_item_impl(ctx, item_id, SMITH))

    assert result["restored_to"] == full
    assert result["price_sp"] > 0
    assert await _inventory_hits(pool, player_id, item_id) == full
    # Exact debit: gold drops by price_sp / silver_per_gold (not merely "some" debit).
    pricing = await get_economy_pricing()
    expected_gold = 100 - result["price_sp"] / pricing["silver_per_gold"]
    row = await pool.fetchrow("SELECT data FROM players WHERE player_id = $1", player_id)
    assert json.loads(row["data"])["gold"] == pytest.approx(expected_gold)


async def test_seeded_magic_items_satisfy_craft_tier_gate(reset_db_pool: str) -> None:
    """Every craftable Rare/Legendary item in the SEEDED catalog joins a tier-correct
    recipe (rare->expert+, legendary->master) — the magic gate against real content."""
    pool = await db.get_pool()
    item_rarity = {r["id"]: json.loads(r["data"]).get("rarity") for r in await pool.fetch("SELECT id, data FROM items")}
    checked = 0
    for r in await pool.fetch("SELECT id, data FROM recipes"):
        recipe = json.loads(r["data"])
        rarity = item_rarity.get(recipe.get("output_item"))
        if rarity in {"rare", "legendary"}:
            result = validate_magic_item_craft_tier(rarity, recipe["tier"])
            assert result.allowed, (
                f"{recipe.get('output_item')} ({rarity}) joins {recipe['tier']} recipe {r['id']}: {result.reason}"
            )
            checked += 1
    assert checked > 0, "expected at least one craftable rare/legendary item to exercise the gate"


# --- http_websocket surface (Bun REST) ---


async def test_rest_repair_quote_matches_agent_price_and_scales_with_rarity(
    durability_server: dict[str, str], reset_db_pool: str
) -> None:
    """The REST repair quote (1) scales with rarity tier (rare > common) and (2) prices
    the same common item identically to the agent tool — both off one rarity SSOT."""
    player_id = "player_repair_http"
    pool = await db.get_pool()
    await seed_player(pool, player_id=player_id, location_id=FORGE)
    headers = {"Authorization": f"Bearer {mint_server_jwt(player_id=player_id)}"}
    base = durability_server["base_url"]

    def _quote(item_id: str) -> dict:
        resp = httpx.get(f"{base}/api/repair/{item_id}?npc={SMITH}", headers=headers, timeout=10.0)
        assert resp.status_code == 200, resp.text
        return resp.json()

    common = _quote("shortsword_basic")  # common
    rare = _quote("hollow_edge_blade")  # rare
    assert common["available"] and rare["available"], (common, rare)
    assert rare["priceSp"] > common["priceSp"]  # rarity tier is load-bearing

    # Value correctness: the REST quote returns the exact rarity SSOT cost for
    # common at neutral disposition (anchors to the SSOT, not just self-parity).
    pricing = await get_economy_pricing()
    expected_common_sp = compute_rental_price(
        pricing["repair_cost_sp"]["common"], "neutral", multipliers=pricing["disposition_multipliers"]
    ).price_sp
    assert common["priceSp"] == expected_common_sp

    # Parity: the Python agent path prices the same common item identically (one SSOT, two surfaces).
    await _set_gold_and_crafting(pool, player_id, gold=100, tier="trained")
    await _seed_inventory_item(pool, player_id, "shortsword_basic", current_hits=2)
    ctx = make_context(player_id=player_id, location_id=FORGE, room=make_mock_room())
    agent_result = json.loads(await _repair_item_impl(ctx, "shortsword_basic", SMITH))
    assert agent_result["price_sp"] == common["priceSp"]
