"""Tests for the travel agent tool (M4.6b / story-003).

`_travel_impl` reads the player + destination, rolls a Survival navigation check, drives the
pure travel.resolve_travel_segment engine, applies exhaustion via the apply_condition SSOT
(capped by exhaustion_stack_cap), persists travel_state, relocates on a successful journey,
and emits a DICE_ROLL event. These tests drive the impl directly with mocked db seams + a
fixed rng, mirroring tests/tools/test_social_tools.py.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, mock_txn, published_events

import event_types as E
from conditions import apply_condition
from tools._helpers import SAMPLE_PLAYER, _make_context
from travel_tools import _travel_impl

_INSPIRED_PLAYER = {**SAMPLE_PLAYER, "conditions": apply_condition([], "inspired")}


def _travel_mocks(player=None):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player if player is not None else SAMPLE_PLAYER)
    mutations = MagicMock()
    mutations.update_player_location = AsyncMock()
    mutations.upsert_map_progress = AsyncMock()
    conditions_mutations = MagicMock()
    conditions_mutations.save_player_conditions = AsyncMock()
    travel_mutations = MagicMock()
    travel_mutations.update_player_travel_state = AsyncMock()
    content = MagicMock()
    content.get_location = AsyncMock(return_value=_location("known_trail"))
    db_mod = MagicMock()
    db_mod.transaction = lambda: mock_txn(MagicMock())
    db_mod.extract_exit_connections = MagicMock(return_value=[])
    return SimpleNamespace(
        queries=queries,
        mutations=mutations,
        conditions_mutations=conditions_mutations,
        travel_mutations=travel_mutations,
        content=content,
        db_mod=db_mod,
    )


def _location(terrain: str):
    return {"id": "dest", "name": "Destination", "terrain": terrain}


def _ctx_with_bus():
    ctx = _make_context()
    ctx.userdata.event_bus = MagicMock()
    return ctx


async def _run(ctx, m, *, destination_id="dest", mode="scenic", hours=4, forced_march=False, rng_val=11):
    return json.loads(
        await _travel_impl(
            ctx,
            destination_id,
            mode,
            hours=hours,
            forced_march=forced_march,
            queries=m.queries,
            mutations=m.mutations,
            conditions_mutations=m.conditions_mutations,
            travel_mutations=m.travel_mutations,
            content=m.content,
            db_mod=m.db_mod,
            rng=FixedRng(rng_val),
        )
    )


# --- Established road: auto-success, no roll, arrives ---


@pytest.mark.asyncio
async def test_established_road_auto_arrives_and_clears_travel_state():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("established_road"))
    ctx = _ctx_with_bus()
    result = await _run(ctx, m, mode="compressed", rng_val=1)  # roll ignored on auto-success
    assert result["outcome"] == "success"
    assert result["arrived"] is True
    m.mutations.update_player_location.assert_awaited_once()
    # Arrival reuses move_player's full path: map progress + the HUD LOCATION_CHANGED event
    # (regression guard for concern 98d6c624a2f2 — the HUD must follow a travelled arrival).
    m.mutations.upsert_map_progress.assert_awaited_once()
    assert any(e.event_type == E.LOCATION_CHANGED for e in published_events(ctx))
    # travel_state cleared to null on arrival
    m.travel_mutations.update_player_travel_state.assert_awaited_once()
    assert m.travel_mutations.update_player_travel_state.await_args.args[1] is None
    # no roll happened → no DICE_ROLL event
    assert not any(e.event_type == E.DICE_ROLL for e in published_events(ctx))


# --- Rolled navigation success: arrives, DICE_ROLL emitted ---


@pytest.mark.asyncio
async def test_rolled_success_arrives_and_emits_dice_roll():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("dense_forest"))  # DC 14
    ctx = _ctx_with_bus()
    result = await _run(ctx, m, mode="scenic", rng_val=20)  # nat-20 → total >= 14
    assert result["outcome"] == "success"
    assert result["arrived"] is True
    assert result["wrong_area"] is False
    m.mutations.update_player_location.assert_awaited_once()
    dice = next(e for e in published_events(ctx) if e.event_type == E.DICE_ROLL)
    assert dice.payload["roll_type"] == "navigation_check"
    assert dice.payload["skill"] == "survival"


# --- Lost failure: no relocation, travel_state records wrong_area ---


@pytest.mark.asyncio
async def test_lost_failure_does_not_relocate_and_persists_wrong_area():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("unmarked_wilderness"))  # DC 12
    ctx = _ctx_with_bus()
    result = await _run(ctx, m, mode="scenic", rng_val=1)  # nat-1 → fail
    assert result["outcome"] == "failure"
    assert result["wrong_area"] is True
    assert result["arrived"] is False
    m.mutations.update_player_location.assert_not_awaited()
    # Lost → no arrival side-effects (HUD stays put, map unrecorded).
    assert not any(e.event_type == E.LOCATION_CHANGED for e in published_events(ctx))
    persisted = m.travel_mutations.update_player_travel_state.await_args.args[1]
    assert persisted is not None and persisted["wrong_area"] is True
    assert persisted["destination"] == "dest"


# --- Exhaustion: applied via apply_condition, capped by exhaustion_stack_cap ---


@pytest.mark.asyncio
async def test_forced_march_long_journey_applies_exhaustion():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("known_trail"))  # DC 8
    ctx = _ctx_with_bus()
    result = await _run(ctx, m, mode="dangerous", hours=12, forced_march=True, rng_val=20)
    assert result["exhaustion_gained"] == 1  # 1 stack per extra 4h beyond 8h
    new_conditions = m.conditions_mutations.save_player_conditions.await_args.args[1]
    exhausted = next(c for c in new_conditions if c["type"] == "exhausted")
    assert exhausted["stacks"] == 1


@pytest.mark.asyncio
async def test_iron_constitution_caps_exhaustion_at_three():
    iron_player = {
        **SAMPLE_PLAYER,
        "skill_tiers": {"endurance": "master"},
        "conditions": [{"type": "exhausted", "duration": None, "source": "prior", "stacks": 3}],
    }
    m = _travel_mocks(player=iron_player)
    m.content.get_location = AsyncMock(return_value=_location("underground"))  # DC 16, exhausts on lost
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="dangerous", rng_val=1)  # lost underground → +1 exhaustion delta
    new_conditions = m.conditions_mutations.save_player_conditions.await_args.args[1]
    exhausted = next(c for c in new_conditions if c["type"] == "exhausted")
    assert exhausted["stacks"] == 3  # capped at 3 (Iron Constitution), not 4


@pytest.mark.asyncio
async def test_clean_success_applies_no_exhaustion():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("known_trail"))
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="scenic", rng_val=20)  # success, no forced march
    m.conditions_mutations.save_player_conditions.assert_not_awaited()


# --- Beneficial-die consume (M4.8 story-010): the nav check spends Inspired's +1d4 ---


@pytest.mark.asyncio
async def test_inspired_nav_consumes_die_without_exhaustion():
    # Clean success (no exhaustion) but Inspired folded +1d4 into the nav check: the die is
    # consumed + persisted (the single conditions write fires for the consume alone).
    m = _travel_mocks(player=_INSPIRED_PLAYER)
    m.content.get_location = AsyncMock(return_value=_location("dense_forest"))  # DC 14 -> a roll happens
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="scenic", rng_val=20)  # success, no forced march
    m.conditions_mutations.save_player_conditions.assert_awaited_once()
    saved = m.conditions_mutations.save_player_conditions.await_args.args[1]
    types = [c["type"] for c in saved]
    assert "inspired" not in types  # die consumed
    assert "exhausted" not in types  # consume alone drove the save — no exhaustion confound


@pytest.mark.asyncio
async def test_inspired_nav_consume_folds_into_exhaustion_write():
    # The load-bearing case: a forced march BOTH accrues exhaustion AND consumes the die. Both
    # mutations must land in ONE save_player_conditions (a second save would clobber the first).
    m = _travel_mocks(player=_INSPIRED_PLAYER)
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="dangerous", hours=12, forced_march=True, rng_val=20)
    m.conditions_mutations.save_player_conditions.assert_awaited_once()
    saved = m.conditions_mutations.save_player_conditions.await_args.args[1]
    types = [c["type"] for c in saved]
    assert "exhausted" in types  # exhaustion applied
    assert "inspired" not in types  # die consumed — neither clobbers the other


@pytest.mark.asyncio
async def test_travel_rebuilds_conditions_from_locked_reread_preserving_concurrent_write():
    # story-013: the exhaustion+consume write-back must re-read conditions under FOR UPDATE inside
    # the tx (not reuse the stale pre-roll read), so a condition applied concurrently (a DM-landed
    # Poisoned) survives instead of being clobbered by the full-list overwrite. The locked re-read
    # AND the save must share the SAME tx connection (atomic with the producer's FOR UPDATE).
    m = _travel_mocks(player=_INSPIRED_PLAYER)
    poisoned = {"type": "poisoned", "duration": None, "source": "dm", "stacks": 1}
    fresh = {**_INSPIRED_PLAYER, "conditions": [*_INSPIRED_PLAYER["conditions"], poisoned]}
    captured: dict = {}

    async def _get_player(_player_id, *, conn=None, for_update=False):
        if for_update:
            captured["conn"] = conn
            return fresh  # the live row — Poisoned landed after the stale pre-roll read
        return _INSPIRED_PLAYER  # the stale read (drives the nav roll + its consume signal)

    m.queries.get_player = AsyncMock(side_effect=_get_player)
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="dangerous", hours=12, forced_march=True, rng_val=20)

    assert captured.get("conn") is not None  # the locked re-read ran with for_update inside the tx
    save = m.conditions_mutations.save_player_conditions
    save.assert_awaited_once()
    types = [c["type"] for c in save.await_args.args[1]]
    assert "poisoned" in types  # concurrent write preserved (rebuilt from the fresh locked read)
    assert "exhausted" in types  # exhaustion applied
    assert "inspired" not in types  # die consumed
    assert save.await_args.kwargs.get("conn") is captured["conn"]  # same tx connection (atomic)


# --- Fail-loud boundaries ---


@pytest.mark.asyncio
async def test_unknown_mode_raises_tool_error():
    m = _travel_mocks()
    with pytest.raises(ToolError):
        await _run(_ctx_with_bus(), m, mode="warp")


@pytest.mark.asyncio
async def test_destination_without_terrain_raises_tool_error():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value={"id": "dest", "name": "No Terrain"})
    with pytest.raises(ToolError):
        await _run(_ctx_with_bus(), m)


@pytest.mark.asyncio
async def test_missing_player_raises_tool_error():
    m = _travel_mocks()
    m.queries.get_player = AsyncMock(return_value=None)
    with pytest.raises(ToolError):
        await _run(_ctx_with_bus(), m)


@pytest.mark.asyncio
async def test_corrupt_conditions_fail_loud_as_toolerror():
    # M4.4 story-008: the nav roll folds Inspired's +1d4 via get_condition_effects, which raw-KeyErrors
    # on a corrupt stored type — validate up front so corruption is a DM-narratable ToolError (the
    # same pre-roll guard the peer check tools keep), not an unhandled stack.
    m = _travel_mocks(player={**SAMPLE_PLAYER, "conditions": [{"type": "bogus"}]})
    m.content.get_location = AsyncMock(return_value=_location("dense_forest"))  # DC 14 -> a roll happens
    with pytest.raises(ToolError, match="corrupt stored conditions"):
        await _run(_ctx_with_bus(), m)
