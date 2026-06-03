"""Tests for mutation-tool helpers and the string/integer bound guards."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import (
    GUILD_PLAYER as SAMPLE_PLAYER,
)
from sample_fixtures import (
    make_context as _make_context,
)
from sample_fixtures import (
    mock_txn as _mock_txn,
)

from check_tools import _request_saving_throw_impl, roll_dice
from inventory_tools import _transact_impl
from progression_tools import _award_divine_favor_impl, _award_xp_impl
from quest_tools import _clamp_disposition_shift
from session_tools import _update_npc_disposition_impl
from tool_support import _cap_str, _resolve_ambient_sounds


class TestClampDispositionShift:
    def test_shift_up(self):
        assert _clamp_disposition_shift("neutral", 1) == "friendly"

    def test_shift_down(self):
        assert _clamp_disposition_shift("neutral", -1) == "wary"

    def test_clamp_at_top(self):
        assert _clamp_disposition_shift("trusted", 2) == "trusted"

    def test_clamp_at_bottom(self):
        assert _clamp_disposition_shift("hostile", -1) == "hostile"

    def test_cautious_normalizes_to_neutral(self):
        # "cautious" shares rank 2 with "neutral" — shifting up from cautious
        assert _clamp_disposition_shift("cautious", 1) == "friendly"

    def test_shift_multiple(self):
        assert _clamp_disposition_shift("hostile", 2) == "neutral"

    def test_unknown_defaults_neutral(self):
        assert _clamp_disposition_shift("unknown", 1) == "friendly"


class TestResolveAmbientSounds:
    def test_daytime_returns_ambient_sounds(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": "harbor_quiet"}
        assert _resolve_ambient_sounds(loc, "evening") == "market_bustle"

    def test_night_returns_night_variant(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": "harbor_quiet"}
        assert _resolve_ambient_sounds(loc, "night") == "harbor_quiet"

    def test_night_without_night_field_falls_back(self):
        loc = {"ambient_sounds": "market_bustle"}
        assert _resolve_ambient_sounds(loc, "night") == "market_bustle"

    def test_missing_ambient_sounds_returns_empty(self):
        loc = {"name": "Some Place"}
        assert _resolve_ambient_sounds(loc, "evening") == ""

    def test_none_location_returns_empty(self):
        assert _resolve_ambient_sounds(None, "evening") == ""

    def test_empty_night_variant_falls_back(self):
        loc = {"ambient_sounds": "market_bustle", "ambient_sounds_night": ""}
        assert _resolve_ambient_sounds(loc, "night") == "market_bustle"


class TestCapStr:
    def test_returns_none_within_limit(self):
        assert _cap_str("hello", 10, "test") is None

    def test_returns_error_over_limit(self):
        with pytest.raises(ToolError, match="256"):
            _cap_str("x" * 300, 256, "reason")

    def test_exact_boundary_is_ok(self):
        assert _cap_str("x" * 256, 256, "reason") is None


class TestStringCaps:
    @pytest.mark.asyncio
    async def test_award_xp_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="reason"):
            await _award_xp_impl(ctx, 50, "x" * 300, db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_award_divine_favor_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _award_divine_favor_impl(
                ctx, 5, "x" * 300, db_mod=MagicMock(), mutations=MagicMock(), activities=MagicMock()
            )

    @pytest.mark.asyncio
    async def test_update_npc_disposition_reason_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _update_npc_disposition_impl(
                ctx,
                "guildmaster_torin",
                1,
                "x" * 300,
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_transact_source_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _transact_impl(
                ctx,
                "health_potion",
                1,
                "x" * 300,
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_roll_dice_notation_too_long(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await roll_dice._func(ctx, notation="x" * 60)


class TestIntegerBounds:
    @pytest.mark.asyncio
    async def test_award_xp_exceeds_max(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="10000"):
            await _award_xp_impl(ctx, 10001, "too much", db_mod=MagicMock(), mutations=MagicMock(), queries=MagicMock())

    @pytest.mark.asyncio
    async def test_award_xp_at_max_is_ok(self):
        """10000 should be accepted (boundary value)."""
        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_mutations = MagicMock()
        mock_mutations.update_player_xp = AsyncMock()
        # A 10000-XP jump levels the skirmisher across L10/L15, so award_xp legitimately
        # applies the crossed auto-grant flags (e.g. extra_attack) via set_player_flag.
        mock_mutations.set_player_flag = AsyncMock()
        ctx = _make_context()
        result = json.loads(
            await _award_xp_impl(
                ctx, 10000, "big reward", db_mod=mock_db, mutations=mock_mutations, queries=mock_queries
            )
        )
        assert "error" not in result
        assert result["amount"] == 10000

    @pytest.mark.asyncio
    async def test_transact_delta_zero(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="non-zero"):
            await _transact_impl(
                ctx,
                "health_potion",
                0,
                "test",
                db_mod=MagicMock(),
                mutations=MagicMock(),
                queries=MagicMock(),
                content=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_transact_magnitude_over_99(self):
        ctx = _make_context()
        # Both signs exceed the magnitude bound.
        for delta in (100, -100):
            with pytest.raises(ToolError, match="magnitude"):
                await _transact_impl(
                    ctx,
                    "health_potion",
                    delta,
                    "test",
                    db_mod=MagicMock(),
                    mutations=MagicMock(),
                    queries=MagicMock(),
                    content=MagicMock(),
                )

    @pytest.mark.asyncio
    async def test_saving_throw_dc_zero(self):
        ctx = _make_context()
        with pytest.raises(ToolError, match="DC"):
            await _request_saving_throw_impl(ctx, "strength", 0, "knocked prone", queries=MagicMock())

    @pytest.mark.asyncio
    async def test_saving_throw_dc_31(self):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _request_saving_throw_impl(ctx, "dexterity", 31, "fireball", queries=MagicMock())
