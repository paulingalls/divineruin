"""Tests for the repair_item agent tool (story-004, M5.4).

repair_item is the NPC-blacksmith repair execution surface (the REST endpoint owns
the price quote). It gates, inside one FOR-UPDATE transaction and before any write
(decision repair-gate-order): locate item by id -> not-repairable -> no-op (already
full) -> disposition (refuse below Neutral, friendly 0.8 / trusted 0.6) -> skill tier
(player Crafting tier >= durability repair tier) -> gold -> restore current_hits to
max + debit. Any refusal raises ToolError (ADR 0002). Pricing reuses
workspace.compute_rental_price + durability.calculate_repair_cost; the debit applies
the disposition multiplier ONCE (quote == REST charge).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

import repair_item


def _item(
    *,
    item_id="longsword_guild",
    rarity="common",
    tier: str | None = "standard",
    current_hits: int | None = 3,
    name="Longsword",
):
    slot = {"quantity": 1, "equipped": True}
    if current_hits is not None:
        slot["current_hits"] = current_hits
    item = {"id": item_id, "name": name, "rarity": rarity, "slot_info": slot}
    if tier is not None:
        item["durability_tier"] = tier
    return item


def _repair_kwargs(*, item, disposition="neutral", crafting_tier="master", gold=15.0, npc_present=True):
    db_mod, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"player_id": "player_1", "gold": gold})
    queries.get_player_inventory = AsyncMock(return_value=[item] if item else [])
    queries.get_npcs_at_location = AsyncMock(return_value=[{"id": "grimjaw"}] if npc_present else [])
    queries.get_npc_disposition = AsyncMock(return_value=disposition)
    queries.get_single_skill_advancement = AsyncMock(return_value={"tier": crafting_tier})
    mutations = MagicMock()
    mutations.update_player_gold = AsyncMock()
    inv_mutations = MagicMock()
    inv_mutations.update_item_durability = AsyncMock()
    content = MagicMock()
    content.get_npc = AsyncMock(return_value=None)
    # Pricing comes from the DB-loaded SSOT (story-011); inject the economy values
    # so the tool's charge math matches the REST quote without a live DB.
    pricing = MagicMock()
    pricing.get_economy_pricing = AsyncMock(
        return_value={
            "repair_cost_sp": {"common": 2, "uncommon": 10, "rare": 50, "legendary": 200},
            "disposition_multipliers": {"friendly": 0.8, "trusted": 0.6},
            "silver_per_gold": 10,
        }
    )
    return (
        {
            "db_mod": db_mod,
            "queries_mod": queries,
            "mutations_mod": mutations,
            "inv_mutations_mod": inv_mutations,
            "content_mod": content,
            "pricing_mod": pricing,
        },
        mutations,
        inv_mutations,
    )


# --- gates: each refusal raises ToolError and writes nothing ------------------


async def test_below_skill_tier_raises_no_writes():
    # reinforced needs Expert; player is untrained. Disposition neutral, item damaged.
    kwargs, mutations, inv_mutations = _repair_kwargs(
        item=_item(tier="reinforced", current_hits=5), crafting_tier="untrained"
    )
    with pytest.raises(ToolError, match="Crafting"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()
    mutations.update_player_gold.assert_not_awaited()


async def test_absent_npc_refuses_no_writes():
    # Co-location gate: a known npc_id who isn't at the player's location can't
    # repair from afar (disposition alone must not gate an absent smith).
    kwargs, mutations, inv_mutations = _repair_kwargs(item=_item(current_hits=3), npc_present=False)
    with pytest.raises(ToolError, match="isn't here"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()
    mutations.update_player_gold.assert_not_awaited()


async def test_below_neutral_disposition_refuses_no_writes():
    kwargs, mutations, inv_mutations = _repair_kwargs(item=_item(current_hits=3), disposition="unfriendly")
    with pytest.raises(ToolError):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()
    mutations.update_player_gold.assert_not_awaited()


async def test_insufficient_gold_raises_no_restore():
    # legendary = 200sp = 20gp; player has 5gp.
    kwargs, mutations, inv_mutations = _repair_kwargs(item=_item(rarity="legendary", current_hits=3), gold=5.0)
    with pytest.raises(ToolError, match="Not enough gold"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()
    mutations.update_player_gold.assert_not_awaited()


async def test_item_not_damaged_refuses():
    kwargs, _, inv_mutations = _repair_kwargs(item=_item(tier="standard", current_hits=10))
    with pytest.raises(ToolError, match="not damaged"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()


async def test_missing_current_hits_reads_as_full_and_refuses():
    kwargs, _, inv_mutations = _repair_kwargs(item=_item(tier="standard", current_hits=None))
    with pytest.raises(ToolError, match="not damaged"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()


async def test_item_not_found_raises():
    kwargs, _, _ = _repair_kwargs(item=None)
    with pytest.raises(ToolError, match="aren't carrying"):
        await repair_item._repair_item_impl(make_context(), "missing_item", "grimjaw", **kwargs)


async def test_non_durable_item_not_repairable():
    kwargs, _, inv_mutations = _repair_kwargs(item=_item(tier=None, current_hits=None))
    with pytest.raises(ToolError, match="cannot be repaired"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()


async def test_malformed_durability_tier_raises_toolerror_not_valueerror():
    kwargs, _, inv_mutations = _repair_kwargs(item=_item(tier="indestructible", current_hits=2))
    with pytest.raises(ToolError, match="unrepairable durability tier"):
        await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    inv_mutations.update_item_durability.assert_not_awaited()


# --- success: restore to max + debit disposition-adjusted gold once -----------


async def test_success_restores_hits_and_debits_gold_once():
    # common=2sp, trusted=0.6x -> 1.2sp = 0.12gp; standard tier max 10; gold 15.
    kwargs, mutations, inv_mutations = _repair_kwargs(
        item=_item(rarity="common", tier="standard", current_hits=3), disposition="trusted", gold=15.0
    )
    raw = await repair_item._repair_item_impl(make_context(), "longsword_guild", "grimjaw", **kwargs)
    result = json.loads(raw)
    assert result == {"item_id": "longsword_guild", "restored_to": 10, "price_sp": pytest.approx(1.2)}
    inv_mutations.update_item_durability.assert_awaited_once()
    assert inv_mutations.update_item_durability.await_args.args[:3] == ("player_1", "longsword_guild", 10)
    mutations.update_player_gold.assert_awaited_once()
    assert mutations.update_player_gold.await_args.args[0] == "player_1"
    assert mutations.update_player_gold.await_args.args[1] == pytest.approx(15.0 - 0.12)


# --- _can_repair_tier (pure) -------------------------------------------------


# --- registration -------------------------------------------------------------


def test_repair_item_registered_on_blacksmith_not_dispatch():
    # story-009 moved repair_item off DISPATCH_TOOLS onto a dedicated BlacksmithAgent.
    from blacksmith_agent import BLACKSMITH_TOOLS
    from dispatch_agent import DISPATCH_TOOLS
    from llm_config import MAX_STRICT_TOOLS

    assert repair_item.repair_item in BLACKSMITH_TOOLS
    assert repair_item.repair_item not in DISPATCH_TOOLS
    assert len(BLACKSMITH_TOOLS) <= MAX_STRICT_TOOLS


# --- _can_repair_tier (pure) -------------------------------------------------


@pytest.mark.parametrize(
    "player_tier,required_tier,expected",
    [
        ("untrained", "trained", False),
        ("trained", "trained", True),
        ("master", "expert", True),
        ("expert", "master", False),
        ("untrained", "untrained", True),
    ],
)
def test_can_repair_tier(player_tier, required_tier, expected):
    assert repair_item._can_repair_tier(player_tier, required_tier) is expected
