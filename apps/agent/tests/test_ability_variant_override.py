"""Tests for the active-variant override in request_ability_activation (M9 story-003).

When a character has an unlocked-and-active mentor variant on a base technique,
activation must deduct the VARIANT's cost (not the base) and return the variant's
narration_cue + cultural_attribution. With no active variant the base path is
unchanged (AC2). Drives the tool's _impl directly with injected mock
db/queries/persistence/variants mods, mirroring test_ability_tools.py; the autouse
seed_abilities fixture supplies the real base-ability map so get_ability resolves.

Base warrior_cleaving_blow costs stamina 4; the Drathian variant costs stamina 5 —
the cost delta is what proves the override actually swapped values.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from sample_fixtures import make_context, make_db_mod

from abilities import Cost
from ability_tools import _request_ability_activation_impl
from mentor_variants import MentorVariant


def _player(stamina: int = 10, focus: int = 10) -> dict:
    return {
        "player_id": "player_1",
        "name": "Kael",
        "class": "warrior",
        "level": 5,
        "stamina": {"current": stamina, "max": 10},
        "focus": {"current": focus, "max": 10},
    }


def _drathian_variant(ability_id: str = "warrior_cleaving_blow") -> MentorVariant:
    return MentorVariant(
        id="warrior_cleaving_blow_drathian",
        ability_id=ability_id,
        mentor_id="mentor_drathian_warleader",
        cost=Cost(stamina=5, focus=0, scaling=None),
        effect="A single melee attack hits up to 2 adjacent enemies — wider and heavier.",
        narration_cue="A brutal Drathian arc, all muscle and momentum.",
        cultural_attribution="Drathian Clans technique",
    )


async def _call(
    ability_id: str,
    *,
    active_variant_id: str | None = None,
    variant: MentorVariant | None = None,
    stamina: int = 10,
    focus: int = 10,
):
    """Invoke the impl with mock mods. Returns (parsed_result, persistence, variants)."""
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=_player(stamina, focus))
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=active_variant_id)
    variants = MagicMock()
    variants.get_variant = MagicMock(return_value=variant)
    raw = await _request_ability_activation_impl(
        ctx,
        ability_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        variants_mod=variants,
    )
    return json.loads(raw), persistence, variants


class TestActiveVariantOverride:
    async def test_active_variant_deducts_variant_cost_and_returns_variant_cue(self):
        # AC1: active Drathian variant overrides base Cleaving Blow (base stamina 4 → variant 5).
        variant = _drathian_variant()
        result, persistence, variants = await _call(
            "warrior_cleaving_blow", active_variant_id=variant.id, variant=variant
        )
        # Override resolved for THIS ability via the contracted accessor.
        variants.get_variant.assert_called_once_with("warrior_cleaving_blow", variant.id)
        # Variant cost (5), not base cost (4), was deducted.
        assert result["deducted"] == {"stamina": 5, "focus": 0}
        assert result["narration_cue"] == variant.narration_cue
        assert result["cultural_attribution"] == "Drathian Clans technique"
        assert result["effect"] == variant.effect
        # The deducted resource write used the variant cost: 10 - 5 = 5 stamina remaining.
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 5

    async def test_variant_cost_insufficient_resource_rejects(self):
        # Variant costs 5 stamina; with only 4 the activation must reject (uses variant cost).
        from livekit.agents.llm import ToolError

        variant = _drathian_variant()
        try:
            await _call("warrior_cleaving_blow", active_variant_id=variant.id, variant=variant, stamina=4)
            raise AssertionError("expected ToolError for insufficient stamina")
        except ToolError as e:
            assert "Stamina" in str(e)

    async def test_active_variant_with_scaling_surfaces_variant_variable_cost(self):
        # The variable_cost contract (concern 7b34ebf86b57) must hold on the override path:
        # a scaling-bearing variant (cost{0,0,scaling}) is NEVER reported as a free activation,
        # and the surfaced variable_cost is the VARIANT's scaling, not the base ability's.
        pool_variant = MentorVariant(
            id="warrior_cleaving_blow_pool",
            ability_id="warrior_cleaving_blow",
            mentor_id="mentor_drathian_warleader",
            cost=Cost(stamina=0, focus=0, scaling="Spend any amount of Stamina; each point widens the arc."),
            effect="A scaling Drathian sweep.",
            narration_cue="The arc widens with every ounce of effort poured in.",
            cultural_attribution="Drathian Clans technique",
        )
        result, persistence, _variants = await _call(
            "warrior_cleaving_blow", active_variant_id=pool_variant.id, variant=pool_variant
        )
        assert result["variable_cost"] == pool_variant.cost.scaling
        # cost{0,0} → no fixed deduction, but the scaling rule still surfaces (not a free activation).
        assert result["deducted"] == {"stamina": 0, "focus": 0}
        persistence.update_player_resources.assert_not_called()


class TestNoActiveVariant:
    async def test_base_path_unchanged_when_no_active_variant(self):
        # AC2: no active variant → base Cleaving Blow cost (4) + base narration_cue, no override keys.
        result, persistence, variants = await _call("warrior_cleaving_blow", active_variant_id=None)
        variants.get_variant.assert_not_called()
        assert result["deducted"] == {"stamina": 4, "focus": 0}
        assert result["narration_cue"]  # base cue
        assert "cultural_attribution" not in result
        assert "effect" not in result
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 6  # 10 - 4 base cost
