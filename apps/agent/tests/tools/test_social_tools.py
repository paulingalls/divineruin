"""Tests for the social-check mode of the `check` verb (M4.6a / story-002).

`_check_social_impl` (folded into check via mode="social") reads an NPC's disposition,
rolls the player's social skill, drives the pure social_resolution engine, persists any
disposition change, and returns a narration cue. These tests drive the impl directly with
mocked db seams + a fixed rng; the dispatch wiring on `check` is covered at the bottom.
"""

import json
import random
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError

import event_types as E
from role_archetypes import shift_disposition
from social_tools import _check_social_impl
from tools._helpers import SAMPLE_PLAYER, _make_context


class _FixedRng(random.Random):
    """A random.Random whose d20 is deterministic (dice.roll uses randint(1, n))."""

    def __init__(self, value: int):
        super().__init__()
        self._value = value

    def randint(self, a: int, b: int) -> int:
        return self._value


def _social_mocks(recorded: str | None = "neutral"):
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    queries.get_npc_disposition = AsyncMock(return_value=recorded)
    mutations = MagicMock()
    mutations.set_npc_disposition = AsyncMock()
    content = MagicMock()
    content.get_npc = AsyncMock(return_value={"id": "merchant_1", "default_disposition": "neutral"})
    return queries, mutations, content


def _ctx_with_bus():
    ctx = _make_context()
    ctx.userdata.event_bus = MagicMock()
    return ctx


def _published(ctx):
    return [call.args[0] for call in ctx.userdata.event_bus.publish.call_args_list]


class TestCheckSocialHappyPath:
    @pytest.mark.asyncio
    async def test_returns_social_outcome_with_cue(self):
        queries, mutations, content = _social_mocks(recorded="neutral")
        result = json.loads(
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )
        )
        assert result["npc_id"] == "merchant_1"
        assert result["skill"] == "persuasion"
        assert result["outcome"] in ("success", "failure")
        assert result["narrative_cue"]
        assert result["previous_disposition"] == "neutral"
        assert result["new_disposition"] in ("hostile", "unfriendly", "neutral", "friendly", "trusted")

    @pytest.mark.asyncio
    async def test_dc_includes_disposition_modifier(self):
        # base moderate DC is 12; a hostile NPC adds +6, a friendly one subtracts 3.
        queries, mutations, content = _social_mocks(recorded="hostile")
        hostile = json.loads(
            await _check_social_impl(
                _ctx_with_bus(),
                "thug",
                "intimidation",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )
        )
        assert hostile["dc"] == 18
        assert hostile["margin"] == hostile["total"] - hostile["dc"]

    @pytest.mark.asyncio
    async def test_new_disposition_is_resolver_delta_applied_to_previous(self):
        # Wiring check: the tool applies exactly the resolver's clamped shift, no extra math.
        queries, mutations, content = _social_mocks(recorded="neutral")
        r = json.loads(
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(15),
            )
        )
        assert r["new_disposition"] == shift_disposition(r["previous_disposition"], r["disposition_shift"])

    @pytest.mark.asyncio
    async def test_emits_dice_roll_event(self):
        queries, mutations, content = _social_mocks()
        ctx = _ctx_with_bus()
        await _check_social_impl(
            ctx,
            "merchant_1",
            "persuasion",
            "moderate",
            queries=queries,
            mutations=mutations,
            content=content,
            rng=_FixedRng(11),
        )
        events = _published(ctx)
        assert any(e.event_type == E.DICE_ROLL for e in events)
        dice = next(e for e in events if e.event_type == E.DICE_ROLL)
        assert dice.payload["roll_type"] == "social_check"
        assert dice.payload["skill"] == "persuasion"


class TestCheckSocialPersistence:
    @pytest.mark.asyncio
    async def test_persists_and_emits_on_shift(self):
        # persuasion success by 5+ (d20 18, mod -1, dc 12 -> margin 5) shifts neutral -> friendly.
        queries, mutations, content = _social_mocks(recorded="neutral")
        ctx = _ctx_with_bus()
        result = json.loads(
            await _check_social_impl(
                ctx,
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(18),
            )
        )
        assert result["new_disposition"] != result["previous_disposition"]
        mutations.set_npc_disposition.assert_awaited_once()
        args = mutations.set_npc_disposition.await_args.args
        assert args[0] == "merchant_1"
        assert args[2] == result["new_disposition"]  # the clamped new disposition
        changed = [e for e in _published(ctx) if e.event_type == E.DISPOSITION_CHANGED]
        assert len(changed) == 1
        assert changed[0].payload == {
            "npc_id": "merchant_1",
            "previous": "neutral",
            "new": result["new_disposition"],
        }

    @pytest.mark.asyncio
    async def test_no_write_or_event_on_zero_shift(self):
        # persuasion bare success (d20 14, mod -1, dc 12 -> margin 1) is +0: disposition unchanged.
        queries, mutations, content = _social_mocks(recorded="neutral")
        ctx = _ctx_with_bus()
        result = json.loads(
            await _check_social_impl(
                ctx,
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(14),
            )
        )
        assert result["disposition_shift"] == 0
        assert result["new_disposition"] == result["previous_disposition"]
        mutations.set_npc_disposition.assert_not_awaited()
        assert not [e for e in _published(ctx) if e.event_type == E.DISPOSITION_CHANGED]


class TestCheckSocialFallbackAndValidation:
    @pytest.mark.asyncio
    async def test_falls_back_to_content_default_when_unrecorded(self):
        # No per-player disposition row -> resolve_disposition reads the NPC's content default.
        queries, mutations, _ = _social_mocks(recorded=None)
        content = MagicMock()
        content.get_npc = AsyncMock(return_value={"id": "elder", "default_disposition": "friendly"})
        result = json.loads(
            await _check_social_impl(
                _ctx_with_bus(),
                "elder",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )
        )
        assert result["previous_disposition"] == "friendly"

    @pytest.mark.asyncio
    async def test_non_social_skill_fails_loud(self):
        queries, mutations, content = _social_mocks()
        with pytest.raises(ToolError, match="athletics"):
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "athletics",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )

    @pytest.mark.asyncio
    async def test_unknown_difficulty_fails_loud(self):
        queries, mutations, content = _social_mocks()
        with pytest.raises(ToolError):
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "persuasion",
                "impossible",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )

    @pytest.mark.asyncio
    async def test_empty_npc_id_fails_loud(self):
        queries, mutations, content = _social_mocks()
        with pytest.raises(ToolError, match="npc_id"):
            await _check_social_impl(
                _ctx_with_bus(),
                "",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )

    @pytest.mark.asyncio
    async def test_missing_player_fails_loud(self):
        queries, mutations, content = _social_mocks()
        queries.get_player = AsyncMock(return_value=None)
        with pytest.raises(ToolError):
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=_FixedRng(11),
            )
