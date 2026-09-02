"""Tests for explicit base and variant activation.

The activation id selects the payload: the base id always uses the base technique,
while the active variant id uses its cost, effect, narration cue, and attribution.
Drives the tool's _impl directly with injected mock
db/queries/persistence/variants mods, mirroring test_ability_tools.py; the autouse
seed_abilities fixture supplies the real base-ability map so get_ability resolves.

Base warrior_cleaving_blow costs stamina 4; the Drathian variant costs stamina 5 —
the cost delta proves the explicit variant path selected its values.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from abilities import Cost, get_ability
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


def _keldaran_variant() -> MentorVariant:
    return MentorVariant(
        id="warrior_cleaving_blow_keldaran",
        ability_id="warrior_cleaving_blow",
        mentor_id="mentor_keldaran_shieldthane",
        cost=Cost(stamina=3, focus=1, scaling=None),
        effect="A measured cleave backed by Keldaran formation craft.",
        narration_cue="The blade moves with disciplined Keldaran precision.",
        cultural_attribution="Keldaran Holds technique",
    )


async def _call(
    ability_id: str,
    *,
    variant_id: str | None = None,
    active_variant_id: str | None = None,
    variant: MentorVariant | None = None,
    stamina: int = 10,
    focus: int = 10,
):
    """Invoke the impl with mock mods. Returns (parsed_result, persistence, variants)."""
    ctx = make_context()
    mock_db, _conn = make_db_mod()
    queries = MagicMock()
    # story-008: the caster row now comes from the id-ordered get_players_for_update batch (self-cast
    # here -> the caster alone).
    row = _player(stamina, focus)
    queries.get_players_for_update = AsyncMock(return_value={row["player_id"]: row})
    persistence = MagicMock()
    persistence.update_player_resources = AsyncMock()
    persistence.get_active_variant = AsyncMock(return_value=active_variant_id)
    # The player owns the base elective (own-the-base gate, story-006); these
    # tests exercise variant selection, not the ownership gate.
    persistence.owns_elective = AsyncMock(return_value=True)
    variants = MagicMock()
    variants.get_variant = MagicMock(return_value=variant)
    raw = await _request_ability_activation_impl(
        ctx,
        ability_id,
        variant_id=variant_id,
        db_mod=mock_db,
        queries_mod=queries,
        persistence_mod=persistence,
        variants_mod=variants,
    )
    return json.loads(raw), persistence, variants


class TestExplicitVariantActivation:
    async def test_active_variant_deducts_variant_cost_and_returns_variant_cue(self):
        variant = _drathian_variant()
        result, persistence, variants = await _call(
            "warrior_cleaving_blow", variant_id=variant.id, active_variant_id=variant.id, variant=variant
        )
        variants.get_variant.assert_called_once_with("warrior_cleaving_blow", variant.id)
        assert result["deducted"] == {"stamina": 5, "focus": 0}
        assert result["narration_cue"] == variant.narration_cue
        assert result["cultural_attribution"] == "Drathian Clans technique"
        assert result["effect"] == variant.effect
        # The deducted resource write used the variant cost: 10 - 5 = 5 stamina remaining.
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 5

    async def test_variant_cost_insufficient_resource_rejects(self):
        variant = _drathian_variant()
        with pytest.raises(ToolError, match="Stamina"):
            await _call(
                "warrior_cleaving_blow",
                variant_id=variant.id,
                active_variant_id=variant.id,
                variant=variant,
                stamina=4,
            )

    async def test_active_variant_with_scaling_surfaces_variant_variable_cost(self):
        # The variable_cost contract (concern 7b34ebf86b57) must hold on the variant path:
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
            "warrior_cleaving_blow",
            variant_id=pool_variant.id,
            active_variant_id=pool_variant.id,
            variant=pool_variant,
        )
        assert result["variable_cost"] == pool_variant.cost.scaling
        # cost{0,0} → no fixed deduction, but the scaling rule still surfaces (not a free activation).
        assert result["deducted"] == {"stamina": 0, "focus": 0}
        persistence.update_player_resources.assert_not_called()

    async def test_variant_id_must_be_the_active_learned_variant(self):
        variant = _drathian_variant()
        with pytest.raises(ToolError, match="active variant"):
            await _call(
                "warrior_cleaving_blow",
                variant_id=variant.id,
                active_variant_id="warrior_cleaving_blow_keldaran",
                variant=variant,
            )


class TestBaseActivation:
    async def test_base_path_uses_base_payload_when_no_active_variant(self):
        result, persistence, variants = await _call("warrior_cleaving_blow")
        variants.get_variant.assert_not_called()
        assert result["deducted"] == {"stamina": 4, "focus": 0}
        assert result["narration_cue"]  # base cue
        assert "cultural_attribution" not in result
        assert result["effect"] == get_ability("warrior_cleaving_blow").effect
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 6

    async def test_base_succeeds_without_focus_despite_active_focus_costing_variant(self):
        variant = _keldaran_variant()
        result, persistence, variants = await _call(
            "warrior_cleaving_blow",
            active_variant_id=variant.id,
            variant=variant,
            focus=0,
        )
        variants.get_variant.assert_not_called()
        persistence.get_active_variant.assert_not_awaited()
        assert result["deducted"] == {"stamina": 4, "focus": 0}
        assert result["effect"] == get_ability("warrior_cleaving_blow").effect
        _args, kwargs = persistence.update_player_resources.call_args
        assert kwargs["stamina"] == 6
