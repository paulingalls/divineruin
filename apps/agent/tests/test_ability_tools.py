"""Tests for request_ability_activation (ability_tools.py).

Drives the tool's _impl directly with a mock RunContext + injected mock
queries/persistence mods (the seed_abilities autouse fixture supplies the real
ability map from content/archetype_abilities.json, so get_ability resolves).

The FIRST test pins the variable/pool-cost contract (concern 7b34ebf86b57): an
ability with cost{0,0}+scaling (paladin_lay_on_hands) must NOT be treated as a
free activation — its scaling rule is surfaced as variable_cost for the DM.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from ability_tools import _request_ability_activation_impl


def _player(stamina: int = 10, focus: int = 10, class_: str = "paladin") -> dict:
    return {
        "player_id": "player_1",
        "name": "Kael",
        "class": class_,
        "level": 5,
        "stamina": {"current": stamina, "max": 10},
        "focus": {"current": focus, "max": 10},
    }


async def _call(
    ability_id: str,
    *,
    stamina: int = 10,
    focus: int = 10,
    player: dict | None = None,
    owns_elective: bool = False,
):
    """Invoke the impl with mock db/queries/persistence. Returns (parsed_result, persistence_mock).

    The own-the-base gate (story-006) requires the player to own the ability. These
    cases activate CORE/reaction abilities, owned via class==archetype — so the
    player's class is derived from the ability id's archetype prefix
    (warrior_*/cleric_*/paladin_*). owns_elective is stubbed (unused on the core path)
    and only consulted for elective abilities.
    """
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    default_player = _player(stamina, focus, class_=ability_id.split("_")[0])
    queries.get_player = AsyncMock(return_value=default_player if player is None else player)
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    # These tests exercise the base (no active variant) path; the override path has its
    # own suite in test_ability_variant_override.py.
    persistence.get_active_variant = AsyncMock(return_value=None)
    persistence.owns_elective = AsyncMock(return_value=owns_elective)
    raw = await _request_ability_activation_impl(
        ctx, ability_id, db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
    )
    return json.loads(raw), persistence


class TestVariableCost:
    async def test_pool_cost_ability_is_not_treated_as_free(self):
        # paladin_lay_on_hands: cost{0,0} with the real cost in free-text scaling.
        # The tool must surface the scaling rule, never report a plain free activation.
        result, persistence = await _call("paladin_lay_on_hands")
        assert result["variable_cost"] is not None
        assert "pool" in result["variable_cost"].lower()
        assert result["deducted"] == {"stamina": 0, "focus": 0}
        # No stamina/focus to deduct, so no resource write happens.
        persistence.update_player_resources.assert_not_called()

    async def test_variable_cost_is_null_for_a_fixed_cost_ability(self):
        result, _ = await _call("warrior_devastating_strike")
        assert result["variable_cost"] is None


class TestActivation:
    async def test_stamina_core_ability_deducts_and_returns_cue(self):
        # warrior_devastating_strike: stamina 3, focus 0.
        result, persistence = await _call("warrior_devastating_strike", stamina=10)
        assert result["deducted"] == {"stamina": 3, "focus": 0}
        assert result["narration_cue"]  # non-empty cue for the DM to voice
        persistence.update_player_resources.assert_awaited_once()
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 7  # 10 - 3
        assert kwargs["focus"] is None  # focus uncosted -> not written (partial-pool safe)

    async def test_reaction_ability_deducts_and_returns_cue(self):
        # warrior_opportunity_strike: reaction, stamina 1 (combat-window gating deferred to Phase 4).
        result, persistence = await _call("warrior_opportunity_strike", stamina=5)
        assert result["deducted"]["stamina"] == 1
        assert result["narration_cue"]
        persistence.update_player_resources.assert_awaited_once()


class TestRejection:
    async def test_insufficient_focus_rejects_without_deducting(self):
        # cleric_heal_wounds: focus 2. Player has only 1 focus.
        with pytest.raises(ToolError):
            await _call("cleric_heal_wounds", focus=1)

    async def test_insufficient_focus_does_not_deduct(self):
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        # Cleric owns the core heal (class==archetype) — so the rejection is the
        # insufficient-focus path, not the own-the-base gate.
        queries.get_player = AsyncMock(return_value=_player(focus=1, class_="cleric"))
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        persistence.get_active_variant = AsyncMock(return_value=None)
        persistence.owns_elective = AsyncMock(return_value=False)
        with pytest.raises(ToolError):
            await _request_ability_activation_impl(
                ctx, "cleric_heal_wounds", db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
            )
        persistence.update_player_resources.assert_not_called()

    async def test_unknown_ability_rejects(self):
        with pytest.raises(ToolError):
            await _call("no_such_ability_xyz")


class TestOwnershipGate:
    """Own-the-base gate on activation (story-006)."""

    async def test_core_ability_rejected_when_class_mismatch(self):
        # A paladin cannot activate a warrior core ability they don't have.
        ctx = make_context()
        mock_db, _conn = make_db_mod()
        queries = MagicMock()
        queries.get_player = AsyncMock(return_value=_player(class_="paladin"))
        persistence = MagicMock()
        persistence.update_player_resources = AsyncMock()
        persistence.get_active_variant = AsyncMock(return_value=None)
        persistence.owns_elective = AsyncMock(return_value=False)
        with pytest.raises(ToolError, match="haven't learned"):
            await _request_ability_activation_impl(
                ctx, "warrior_devastating_strike", db_mod=mock_db, queries_mod=queries, persistence_mod=persistence
            )
        persistence.update_player_resources.assert_not_called()

    async def test_elective_rejected_when_not_owned(self):
        # The base elective has no character_abilities row → reject before deducting.
        result_raises = False
        try:
            await _call("warrior_cleaving_blow", owns_elective=False)
        except ToolError as e:
            result_raises = "haven't learned" in str(e)
        assert result_raises, "expected ToolError for an unowned elective"

    async def test_elective_allowed_when_owned(self):
        # With the character_abilities row present, the elective activates normally.
        result, persistence = await _call("warrior_cleaving_blow", owns_elective=True)
        assert result["deducted"]["stamina"] == 4  # base Cleaving Blow cost
        persistence.update_player_resources.assert_awaited_once()
