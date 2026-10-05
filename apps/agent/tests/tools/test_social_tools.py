"""Database seams are mocked; dispatch and the social implementation are real."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import FixedRng, published_events

import event_types as E
from check_tools import VALID_CHECK_MODES, _check_impl
from role_archetypes import shift_disposition
from social_tools import _check_social_impl
from tools._helpers import _ctx_with_bus, _social_mocks


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
                rng=FixedRng(11),
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
                rng=FixedRng(11),
            )
        )
        assert hostile["dc"] == 18
        assert hostile["margin"] == hostile["total"] - hostile["dc"]

    @pytest.mark.asyncio
    async def test_new_disposition_is_resolver_delta_applied_to_previous(self):
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
                rng=FixedRng(15),
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
            rng=FixedRng(11),
        )
        events = published_events(ctx)
        assert any(e.event_type == E.DICE_ROLL for e in events)
        dice = next(e for e in events if e.event_type == E.DICE_ROLL)
        assert dice.payload["roll_type"] == "social_check"
        assert dice.payload["skill"] == "persuasion"


class TestCheckSocialPersistence:
    @pytest.mark.asyncio
    async def test_persists_and_emits_on_shift(self):
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
                rng=FixedRng(18),
            )
        )
        assert result["new_disposition"] != result["previous_disposition"]
        mutations.set_npc_disposition.assert_awaited_once()
        args = mutations.set_npc_disposition.await_args.args
        assert args[0] == "merchant_1"
        assert args[2] == result["new_disposition"]  # the clamped new disposition
        changed = [e for e in published_events(ctx) if e.event_type == E.DISPOSITION_CHANGED]
        assert len(changed) == 1
        assert changed[0].payload == {
            "npc_id": "merchant_1",
            "previous": "neutral",
            "new": result["new_disposition"],
        }

    @pytest.mark.asyncio
    async def test_no_write_or_event_on_zero_shift(self):
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
                rng=FixedRng(14),
            )
        )
        assert result["disposition_shift"] == 0
        assert result["new_disposition"] == result["previous_disposition"]
        mutations.set_npc_disposition.assert_not_awaited()
        assert not [e for e in published_events(ctx) if e.event_type == E.DISPOSITION_CHANGED]


class TestCheckSocialFallbackAndValidation:
    @pytest.mark.asyncio
    async def test_falls_back_to_content_default_when_unrecorded(self):
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
                rng=FixedRng(11),
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
                rng=FixedRng(11),
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
                rng=FixedRng(11),
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
                rng=FixedRng(11),
            )

    @pytest.mark.asyncio
    async def test_offladder_disposition_fails_loud_as_toolerror(self):
        queries, mutations, content = _social_mocks(recorded="wary")
        with pytest.raises(ToolError, match="disposition"):
            await _check_social_impl(
                _ctx_with_bus(),
                "merchant_1",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=FixedRng(11),
            )

    @pytest.mark.asyncio
    async def test_malformed_npc_id_fails_loud(self):
        queries, mutations, content = _social_mocks()
        with pytest.raises(ToolError, match="npc_id"):
            await _check_social_impl(
                _ctx_with_bus(),
                "drop;tables",
                "persuasion",
                "moderate",
                queries=queries,
                mutations=mutations,
                content=content,
                rng=FixedRng(11),
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
                rng=FixedRng(11),
            )


class TestCheckSocialDispatch:
    @pytest.mark.asyncio
    async def test_check_mode_social_routes_to_social_impl(self):
        queries, mutations, content = _social_mocks()
        result = json.loads(
            await _check_impl(
                _ctx_with_bus(),
                "social",
                skill="persuasion",
                difficulty="moderate",
                npc_id="merchant_1",
                queries=queries,
                mutations=mutations,
                content=content,
            )
        )
        assert result["npc_id"] == "merchant_1"
        assert "narrative_cue" in result
        assert "new_disposition" in result

    @pytest.mark.asyncio
    async def test_social_is_a_registered_mode(self):
        assert "social" in VALID_CHECK_MODES
