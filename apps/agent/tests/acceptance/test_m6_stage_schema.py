"""Capstone: Milestone 6 stage-schema, system-wide (story-004).

Proves all four M6 done-criteria hold end-to-end against ONE seeded location —
the §7 Stage the per-story tests (001-003) can't prove whole individually:

  - AC1: the warm layer's AFFORDANCES are grouped by verb and the danger is a
    BAND word (not a raw integer); a gated exit renders as a `check` target,
    a hidden element never leaks into narration;
  - AC2: a successful discover check against the attached element emits
    E.HIDDEN_REVEALED AND surfaces the revealed id in the hot layer same-turn,
    then clears it;
  - AC3: once the gated exit's requirement is MET, a warm rebuild moves the exit
    from `check` to `go` (the gate-evaluation edge story-003 left open);
  - AC4: the full Stage pipeline — assemble → discover → rebuild — runs green as
    one loop, the discovery's own reveal flag unlocking the gated exit.

Runs over the seeded testcontainer DB (`reset_db_pool`); skips cleanly when
Docker is down (postgres_container fixture). The discover roll is made
deterministic by pinning the d20 via the `check_resolution.dice_roll` seam — the
element's anti-grind gate consumes the roll once, so a natural-1 auto-fail would
otherwise flake AC2/AC4.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from acceptance.seeds import seed_player
from sample_fixtures import make_context

import check_resolution
import db
import db_mutations
import event_types as E
from bg_event_handlers import handle_events
from check_discovery import _check_discover_impl
from dice import DiceResult
from errand_risk import numeric_to_danger
from gameplay_agent import GameplayAgent
from warm_prompts import build_warm_layer

_PLAYER_ID = "player_m6_capstone"
_LOCATION_ID = "test_m6_stage_location"
_SEAL_ID = "test_seal"
_TARGET = "arch"  # the bare attaches_to token
# The player examines the feature using the DM-advertised key_feature prose; whole-word
# containment of the attaches_to token ("arch") makes discovery fire on natural phrasing.
_PROSE_TARGET = "the cracked stone arch to the north"

# One seeded Stage: a visible arch (key_feature) with a hidden seal attached to it,
# an ungated exit (`out`, a `go` affordance) and a gated exit (`deeper`) whose
# requirement is the seal's own discovery flag — so discovering the seal unlocks it.
_M6_LOCATION = {
    "id": _LOCATION_ID,
    "name": "Sundered Antechamber",
    "tier": 1,
    "district": "test",
    "region": "test",
    "danger_level": 2,  # -> "dangerous" band
    "atmosphere": "cold stone and the slow drip of water",
    "description": "A low vault of cracked stone, the air thick with dust.",
    "key_features": ["a cracked stone arch to the north"],
    "hidden_elements": [
        {
            "id": _SEAL_ID,
            "discover_skill": "perception",
            "dc": 10,
            "description": "a veythar seal etched into the keystone behind the arch",
            "attaches_to": _TARGET,
        }
    ],
    "exits": {
        "out": {"destination": "accord_market_square"},
        "deeper": {"destination": "greyvale_ruins_inner", "requires": f"{_SEAL_ID}.discovered"},
    },
    "tags": ["test"],
}


@pytest.fixture
async def m6_world(reset_db_pool: str) -> AsyncIterator[str]:
    """Seed the M6 player + Stage location, yield the location id, then clean up.

    Unique player/location ids keep the capstone isolated from other acceptance
    tests sharing the session DB; teardown drops both rows so the gated-exit flag
    never leaks into a later run.
    """
    pool = await db.get_pool()
    await seed_player(pool, player_id=_PLAYER_ID, location_id=_LOCATION_ID)
    await pool.execute(
        """
        INSERT INTO locations (id, data) VALUES ($1, $2::jsonb)
        ON CONFLICT (id) DO UPDATE SET data = $2::jsonb
        """,
        _LOCATION_ID,
        json.dumps(_M6_LOCATION),
    )
    try:
        yield _LOCATION_ID
    finally:
        await pool.execute("DELETE FROM locations WHERE id = $1", _LOCATION_ID)
        await pool.execute("DELETE FROM players WHERE player_id = $1", _PLAYER_ID)


def _force_discovery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the discover d20 to a fixed mid roll (not a nat-1/nat-20) so the check
    succeeds deterministically against the seeded DC — we are proving the §7 loop,
    not the RNG."""
    monkeypatch.setattr(
        check_resolution,
        "dice_roll",
        lambda notation, rng=None: DiceResult(notation=notation, rolls=[15], dropped=[], total=15),
    )


async def _warm(location_id: str) -> str:
    """Assemble the warm layer for the seeded Stage (pre-fetched location, no NPCs)."""
    return await build_warm_layer(
        location_id,
        _PLAYER_ID,
        "evening",
        location=dict(_M6_LOCATION),
        npcs_raw=[],
        quests=[],
    )


async def test_ac1_affordances_verb_grouped_and_banded(m6_world: str) -> None:
    """AC1: affordances are verb-grouped, danger is a band, the gated exit is a
    `check` target, and the hidden element never reaches narration."""
    warm = await _warm(m6_world)

    assert "AFFORDANCES" in warm
    # Ungated exit -> go; gated exit -> check (locked), never go (pre-discovery).
    assert "go: " in warm
    assert "out → accord_market_square" in warm
    assert "check: " in warm
    assert "deeper (locked)" in warm  # gated exit is a check target, sanitized
    assert "a cracked stone arch to the north" in warm  # key_feature is a check target

    # Danger renders as a BAND word, not the raw integer.
    assert f"danger: {numeric_to_danger(2)}" in warm
    assert numeric_to_danger(2) == "dangerous"

    # §7: neither the hidden element's prose NOR its id reaches the DM-facing layer. The
    # locked exit no longer leaks the raw `requires` (which named the seal), so the id is
    # absent from the WHOLE warm string, not just the narration section.
    assert "veythar seal" not in warm
    assert "etched into the keystone" not in warm
    assert _SEAL_ID not in warm


async def test_ac2_discovery_reveals_and_surfaces_in_hot_layer_same_turn(
    m6_world: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: a successful discover emits E.HIDDEN_REVEALED, and the revealed id is
    in the hot layer the same turn, then cleared."""
    _force_discovery_success(monkeypatch)
    ctx = make_context(player_id=_PLAYER_ID, location_id=m6_world)
    sd = ctx.userdata

    # Examine via the DM-advertised prose; whole-word containment still surfaces the seal.
    result = json.loads(await _check_discover_impl(ctx, skill="perception", target=_PROSE_TARGET))
    assert result["outcome"] == "discovered"
    assert result["element_id"] == _SEAL_ID

    # E.HIDDEN_REVEALED fired on the session's event bus.
    events = sd.event_bus.drain()
    revealed = [e for e in events if e.event_type == E.HIDDEN_REVEALED]
    assert len(revealed) == 1
    assert revealed[0].payload["element_id"] == _SEAL_ID

    # Background handler records the reveal + asks for a rebuild...
    needs_rebuild, _ = handle_events(events, sd, [], False, {}, [])
    assert needs_rebuild is True
    assert _SEAL_ID in sd.recently_revealed_element_ids

    # ...and the hot layer surfaces it THIS turn, then clears so it doesn't echo.
    # _build_hot_context reads only `sd` (zero I/O), so call it unbound.
    hot = GameplayAgent._build_hot_context(None, sd)  # type: ignore[arg-type]
    assert f"[Revealed: {_SEAL_ID}]" in hot
    assert sd.recently_revealed_element_ids == []


async def test_ac3_met_requirement_promotes_exit_check_to_go(m6_world: str) -> None:
    """AC3: once the gated exit's requirement is met, a rebuild moves it check -> go."""
    # Pre-condition: the gate is locked (sanitized label, no raw requires leak).
    before = await _warm(m6_world)
    assert "deeper (locked)" in before
    assert _SEAL_ID not in before

    # Meet the requirement directly (independent of the discovery path).
    await db_mutations.set_player_flag(_PLAYER_ID, f"{_SEAL_ID}.discovered", True)

    after = await _warm(m6_world)
    assert "deeper → greyvale_ruins_inner" in after
    assert "deeper (locked:" not in after


async def test_ac4_full_stage_pipeline_e2e(m6_world: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: the whole §7 loop green — assemble (locked) -> discover (reveal) ->
    rebuild (unlocked), the discovery's own flag unlocking the gated exit."""
    _force_discovery_success(monkeypatch)
    ctx = make_context(player_id=_PLAYER_ID, location_id=m6_world)
    sd = ctx.userdata

    # 1. Stage assembled: gated exit locked (sanitized — no raw requires/hidden id leak).
    locked = await _warm(m6_world)
    assert "deeper (locked)" in locked
    assert _SEAL_ID not in locked

    # 2. Discover the seal via the advertised prose: reveal fires + hot-layer same-turn.
    result = json.loads(await _check_discover_impl(ctx, skill="perception", target=_PROSE_TARGET))
    assert result["outcome"] == "discovered"
    needs_rebuild, _ = handle_events(sd.event_bus.drain(), sd, [], False, {}, [])
    assert needs_rebuild is True
    assert f"[Revealed: {_SEAL_ID}]" in GameplayAgent._build_hot_context(None, sd)  # type: ignore[arg-type]

    # 3. Warm rebuild: the discovery flag now unlocks the gated exit (check -> go).
    unlocked = await _warm(m6_world)
    assert "deeper → greyvale_ruins_inner" in unlocked
    assert "deeper (locked:" not in unlocked
