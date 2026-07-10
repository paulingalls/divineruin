"""Capstone: M4.6b Travel & Exploration end-to-end against a real Postgres testcontainer.

Stories 001-003 shipped the travel surface in slices: the pure resolver (001), the data
substrate (migration 055 + location terrain, 002), and the travel tool + apply_arrival reuse
(003). This capstone proves they COMPOSE on ONE seeded testcontainer (auto-marked `acceptance`),
driving the REAL travel pipeline against real DB writes across a multi-segment journey:

- AC1: a clean-success segment (established_road) auto-arrives, relocates the player, clears
  travel_state, and emits LOCATION_CHANGED so the HUD follows the arrival.
- AC2: a forced-march navigation failure (dense_forest, low roll) is lost — wrong_area, no
  relocation, travel_state records the failed destination, and forced-march exhaustion accrues.
- AC3: exhaustion accrues across segments in players.data.conditions and never exceeds the
  character's Iron-Constitution stack cap (3).

Determinism: the d20 navigation check is forced via an injected rng (FixedRng) — 20 passes,
1 fails. Exhaustion on the seeded terrains comes from forced march (>8h), since only
underground/hollow_corrupted self-exhaust on a lost failure. Each test uses a distinct
player_id (the testcontainer DB is shared).
"""

from __future__ import annotations

import json

from acceptance.seeds import seed_player
from sample_fixtures import FixedRng, make_context, make_mock_room, published_payloads

import db
import db_queries
import event_types as E
import travel_tools

# Travel-reachable locations seeded with terrain by story-002 (content/locations.json).
_ROAD = "greyvale_south_road"  # terrain: established_road (auto-success, no roll)
_DENSE = "greyvale_wilderness_north"  # terrain: dense_forest (nav DC 14)
_RUINS = "greyvale_ruins_exterior"  # terrain: unmarked_wilderness (start)


async def _set_endurance_master(pool, player_id: str) -> None:
    """Give the player the Endurance master tier (Iron Constitution) → Exhausted caps at 3."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{skill_tiers}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"endurance": "master"}),
    )


def _exhausted(player: dict) -> dict | None:
    return next((c for c in (player.get("conditions") or []) if c["type"] == "exhausted"), None)


async def test_m46b_clean_road_segment_arrives_and_clears_travel_state(reset_db_pool: str) -> None:
    """AC1: an established-road segment auto-succeeds, relocates, clears travel_state, updates the HUD."""
    pool = await db.get_pool()
    player_id = "cap_m46b_road"
    await seed_player(pool, player_id=player_id, class_="skirmisher", location_id=_RUINS)

    ctx = make_context(player_id, location_id=_RUINS, room=make_mock_room())
    result = json.loads(await travel_tools._travel_impl(ctx, _ROAD, "compressed", hours=4, rng=FixedRng(1)))

    assert result["outcome"] == "success"
    assert result["arrived"] is True
    assert result["wrong_area"] is False

    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None
    assert player["location_id"] == _ROAD  # relocated via the shared arrival path
    assert player.get("travel_state") is None  # cleared on arrival
    assert _exhausted(player) is None  # a clean non-forced trip accrues no exhaustion

    # The HUD follows the arrival (apply_arrival emits LOCATION_CHANGED). established_road has no
    # navigation roll, so NO navigation DICE_ROLL is expected here.
    events = published_payloads(ctx.userdata.room)
    assert any(e.get("type") == E.LOCATION_CHANGED for e in events)
    assert not [e for e in events if e.get("type") == E.DICE_ROLL]


async def test_m46b_forced_march_failure_is_lost_and_exhausts(reset_db_pool: str) -> None:
    """AC2: a forced-march nav failure is lost (wrong_area), does not relocate, and exhausts."""
    pool = await db.get_pool()
    player_id = "cap_m46b_lost"
    await seed_player(pool, player_id=player_id, class_="skirmisher", location_id=_RUINS)

    ctx = make_context(player_id, location_id=_RUINS, room=make_mock_room())
    result = json.loads(
        await travel_tools._travel_impl(ctx, _DENSE, "dangerous", hours=12, forced_march=True, rng=FixedRng(1))
    )

    assert result["outcome"] == "failure"
    assert result["wrong_area"] is True
    assert result["arrived"] is False
    assert result["exhaustion_gained"] == 1  # forced march 12h → (12-8)//4 = 1 stack

    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None
    assert player["location_id"] == _RUINS  # lost → no relocation
    travel_state = player.get("travel_state")
    assert travel_state is not None
    assert travel_state["destination"] == _DENSE
    assert travel_state["mode"] == "dangerous"
    assert travel_state["wrong_area"] is True

    exhausted = _exhausted(player)
    assert exhausted is not None
    assert exhausted["stacks"] == 1
    assert exhausted["source"] == "travel"

    # dense_forest has a DC, so the navigation roll surfaced on the HUD as a failed check.
    nav = [e for e in published_payloads(ctx.userdata.room) if e.get("type") == E.DICE_ROLL]
    assert nav and nav[0]["roll_type"] == "navigation_check" and nav[0]["success"] is False


async def test_m46b_exhaustion_accrues_across_segments_and_respects_iron_cap(reset_db_pool: str) -> None:
    """AC3 / E2E: forced-march exhaustion accumulates across segments, capped at 3 (Iron Constitution)."""
    pool = await db.get_pool()
    player_id = "cap_m46b_iron"
    await seed_player(pool, player_id=player_id, class_="skirmisher", location_id=_RUINS)
    await _set_endurance_master(pool, player_id)  # Exhausted caps at 3

    ctx = make_context(player_id, location_id=_RUINS, room=make_mock_room())

    # Segment 1: forced march 12h to the road (established_road auto-succeeds) → +1 stack, arrives.
    r1 = json.loads(
        await travel_tools._travel_impl(ctx, _ROAD, "dangerous", hours=12, forced_march=True, rng=FixedRng(20))
    )
    assert r1["arrived"] is True and r1["exhaustion_gained"] == 1
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None
    exhausted = _exhausted(player)
    assert exhausted is not None and exhausted["stacks"] == 1
    assert player["location_id"] == _ROAD

    # Segment 2: forced march 16h to dense_forest, passing roll (rng 20) → delta 2, 1→3 (capped).
    r2 = json.loads(
        await travel_tools._travel_impl(ctx, _DENSE, "dangerous", hours=16, forced_march=True, rng=FixedRng(20))
    )
    assert r2["arrived"] is True and r2["exhaustion_gained"] == 2
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None
    exhausted = _exhausted(player)
    assert exhausted is not None and exhausted["stacks"] == 3  # 1 + 2 = 3, at the Iron-Constitution cap
    assert player["location_id"] == _DENSE

    # Segment 3: another 16h forced march (delta 2) → already at cap, stays 3.
    await travel_tools._travel_impl(ctx, _ROAD, "dangerous", hours=16, forced_march=True, rng=FixedRng(1))
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None
    exhausted = _exhausted(player)
    assert exhausted is not None and exhausted["stacks"] == 3  # capped — never exceeds 3
