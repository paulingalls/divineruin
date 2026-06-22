"""Tests for the travel agent tool (M4.6b / story-003).

`_travel_impl` reads the player + destination, rolls a Survival navigation check, drives the
pure travel.resolve_travel_segment engine, applies exhaustion via the apply_condition SSOT
(capped by exhaustion_stack_cap), persists travel_state, relocates on a successful journey,
and emits a DICE_ROLL event. These tests drive the impl directly with mocked db seams + a
fixed rng, mirroring tests/tools/test_social_tools.py.
"""

import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from tools._helpers import SAMPLE_PLAYER, _make_context
from travel_tools import _travel_impl


class _FixedRng(random.Random):
    """A random.Random whose d20 is deterministic (dice.roll uses randint(1, n))."""

    def __init__(self, value: int):
        super().__init__()
        self._value = value

    def randint(self, a: int, b: int) -> int:
        return self._value


def _travel_mocks(player=None):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=player if player is not None else SAMPLE_PLAYER)
    mutations = MagicMock()
    mutations.update_player_conditions = AsyncMock()
    mutations.update_player_travel_state = AsyncMock()
    mutations.update_player_location = AsyncMock()
    content = MagicMock()
    content.get_location = AsyncMock(return_value=_location("known_trail"))
    return SimpleNamespace(queries=queries, mutations=mutations, content=content)


def _location(terrain: str):
    return {"id": "dest", "name": "Destination", "terrain": terrain}


def _ctx_with_bus():
    ctx = _make_context()
    ctx.userdata.event_bus = MagicMock()
    return ctx


def _published(ctx):
    return [call.args[0] for call in ctx.userdata.event_bus.publish.call_args_list]


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
            content=m.content,
            rng=_FixedRng(rng_val),
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
    # travel_state cleared to null on arrival
    m.mutations.update_player_travel_state.assert_awaited_once()
    assert m.mutations.update_player_travel_state.await_args.args[1] is None
    # no roll happened → no DICE_ROLL event
    assert not any(e.event_type == E.DICE_ROLL for e in _published(ctx))


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
    dice = next(e for e in _published(ctx) if e.event_type == E.DICE_ROLL)
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
    persisted = m.mutations.update_player_travel_state.await_args.args[1]
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
    new_conditions = m.mutations.update_player_conditions.await_args.args[1]
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
    new_conditions = m.mutations.update_player_conditions.await_args.args[1]
    exhausted = next(c for c in new_conditions if c["type"] == "exhausted")
    assert exhausted["stacks"] == 3  # capped at 3 (Iron Constitution), not 4


@pytest.mark.asyncio
async def test_clean_success_applies_no_exhaustion():
    m = _travel_mocks()
    m.content.get_location = AsyncMock(return_value=_location("known_trail"))
    ctx = _ctx_with_bus()
    await _run(ctx, m, mode="scenic", rng_val=20)  # success, no forced march
    m.mutations.update_player_conditions.assert_not_awaited()


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
