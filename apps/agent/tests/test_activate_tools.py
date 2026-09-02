"""Tests for activate_tools.activate — the polymorphic Phase-5 dispatcher (M25 story-001).

activate(id) is a pure router: it resolves an id to a kind (reserved token, Veil Anchor, spell,
ability, or mentor variant) and dispatches to the matching pre-existing ``_impl``. No transaction
of its own — each target ``_impl`` still opens and commits its own. Routing is mostly proven with
injected stub impls (AsyncMock); each target ``_impl`` already has its own test suite for its own
behavior. The one exception is the variant namespace, whose id resolution is also pinned against
the real loaded catalog so mocking both sides cannot hide a content/routing drift.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError, is_function_tool, is_raw_function_tool
from sample_fixtures import make_context

import abilities
import mentor_variants
import spells
import veil_ward
from activate_tools import _activate_impl, _resolve_kind, activate


def _mocks() -> tuple[dict[str, Any], dict[str, AsyncMock]]:
    # dict[str, Any] on the first member — not dict[str, "SimpleImpl"] — so pyright doesn't treat
    # this literal's keys as candidate values for _call's *other* typed kwargs (spells_mod,
    # abilities_mod) when it's spread with **mods below.
    cast_spell = AsyncMock(return_value="spell-result")
    request_ability = AsyncMock(return_value="ability-result")
    deploy_anchor = AsyncMock(return_value="anchor-result")
    activate_ward = AsyncMock(return_value="ward-result")
    inner_fire = AsyncMock(return_value="fire-result")
    return {
        "cast_spell_mod": SimpleImpl(cast_spell),
        "ability_mod": SimpleImpl(request_ability),
        "anchor_mod": SimpleImpl(deploy_anchor),
        "ward_mod": SimpleImpl(activate_ward),
        "inner_fire_mod": SimpleImpl(inner_fire),
    }, {
        "cast_spell": cast_spell,
        "request_ability": request_ability,
        "deploy_anchor": deploy_anchor,
        "activate_ward": activate_ward,
        "inner_fire": inner_fire,
    }


class SimpleImpl:
    """Stands in for a target module, exposing exactly the one _impl attr activate_tools calls."""

    def __init__(self, fn):
        self._fn = fn

    def __getattr__(self, name):
        return self._fn


async def _call(
    id_,
    *,
    target_id=None,
    target_ids=None,
    spells_mod=spells,
    abilities_mod=abilities,
    variants_mod=mentor_variants,
    **mods,
):
    ctx = make_context()
    result = await _activate_impl(
        ctx,
        id_,
        target_id=target_id,
        target_ids=target_ids,
        spells_mod=spells_mod,
        abilities_mod=abilities_mod,
        variants_mod=variants_mod,
        **mods,
    )
    return ctx, result


class TestSpellRouting:
    async def test_spell_id_dispatches_to_cast_spell_impl(self):
        mods, fns = _mocks()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=object())
        ctx, result = await _call("firebolt", target_id="goblin_1", spells_mod=spells_mod, **mods)
        assert result == "spell-result"
        fns["cast_spell"].assert_awaited_once_with(ctx, "firebolt", target_id="goblin_1", target_ids=None)

    async def test_spell_target_ids_pass_through(self):
        mods, fns = _mocks()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(return_value=object())
        ctx, _result = await _call("bless", target_ids=["a", "b"], spells_mod=spells_mod, **mods)
        fns["cast_spell"].assert_awaited_once_with(ctx, "bless", target_id=None, target_ids=["a", "b"])


class TestAbilityRouting:
    async def test_ability_id_dispatches_to_request_ability_activation_impl(self):
        mods, fns = _mocks()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(side_effect=ValueError("unknown spell"))
        abilities_mod = MagicMock()
        abilities_mod.get_ability = MagicMock(return_value=object())
        ctx, result = await _call(
            "warrior_devastating_strike", target_id="orc_1", spells_mod=spells_mod, abilities_mod=abilities_mod, **mods
        )
        assert result == "ability-result"
        fns["request_ability"].assert_awaited_once_with(
            ctx, "warrior_devastating_strike", target_id="orc_1", target_ids=None
        )


class TestVariantRouting:
    async def test_variant_id_dispatches_base_ability_with_explicit_variant(self):
        mods, fns = _mocks()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(side_effect=ValueError("unknown spell"))
        abilities_mod = MagicMock()
        abilities_mod.get_ability = MagicMock(side_effect=ValueError("unknown ability"))
        variants_mod = MagicMock()
        variant = MagicMock(ability_id="warrior_cleaving_blow")
        variants_mod.get_mentor_variant = MagicMock(return_value=variant)

        ctx, result = await _call(
            "warrior_cleaving_blow_keldaran",
            target_id="orc_1",
            spells_mod=spells_mod,
            abilities_mod=abilities_mod,
            variants_mod=variants_mod,
            **mods,
        )

        assert result == "ability-result"
        fns["request_ability"].assert_awaited_once_with(
            ctx,
            "warrior_cleaving_blow",
            variant_id="warrior_cleaving_blow_keldaran",
            target_id="orc_1",
            target_ids=None,
        )

    async def test_real_content_variant_id_routes_against_the_loaded_catalog(self):
        # The mocked test above proves the dispatch shape but would stay green if the real
        # catalog never held the id, so pin the content->routing link with nothing injected:
        # the conftest fixture loads content/mentor_variants.json the way startup loads the DB.
        variant = mentor_variants.get_mentor_variant("warrior_cleaving_blow_keldaran")
        kinds = {
            id_: _resolve_kind(
                id_,
                spells_mod=spells,
                abilities_mod=abilities,
                variants_mod=mentor_variants,
                anchors_mod=veil_ward,
            )
            for id_ in (variant.id, variant.ability_id)
        }
        assert kinds == {variant.id: "variant", variant.ability_id: "ability"}


class TestAnchorRouting:
    async def test_anchor_item_id_dispatches_to_deploy_veil_anchor_impl(self):
        mods, fns = _mocks()
        ctx, result = await _call("veil_ward_anchor_small", **mods)
        assert result == "anchor-result"
        fns["deploy_anchor"].assert_awaited_once_with(ctx, "veil_ward_anchor_small")

    async def test_large_anchor_also_routes(self):
        mods, fns = _mocks()
        ctx, result = await _call("veil_ward_anchor_large", **mods)
        assert result == "anchor-result"
        fns["deploy_anchor"].assert_awaited_once_with(ctx, "veil_ward_anchor_large")


class TestReservedTokenRouting:
    async def test_veil_ward_raises(self):
        mods, fns = _mocks()
        ctx, result = await _call("veil_ward", target_id="cleric_1", **mods)
        assert result == "ward-result"
        fns["activate_ward"].assert_awaited_once_with(ctx, active=True, caster_id="cleric_1")

    async def test_veil_ward_dismiss(self):
        mods, fns = _mocks()
        ctx, result = await _call("veil_ward_dismiss", target_id="cleric_1", **mods)
        assert result == "ward-result"
        fns["activate_ward"].assert_awaited_once_with(ctx, active=False, caster_id="cleric_1")

    async def test_veil_ward_with_no_target_defaults_caster_to_none(self):
        mods, fns = _mocks()
        ctx, _result = await _call("veil_ward", **mods)
        fns["activate_ward"].assert_awaited_once_with(ctx, active=True, caster_id=None)

    async def test_draethar_inner_fire(self):
        mods, fns = _mocks()
        ctx, result = await _call("draethar_inner_fire", **mods)
        assert result == "fire-result"
        fns["inner_fire"].assert_awaited_once_with(ctx)


class TestUnknownId:
    async def test_unknown_id_raises_tool_error_before_any_dispatch(self):
        mods, fns = _mocks()
        spells_mod = MagicMock()
        spells_mod.get_spell = MagicMock(side_effect=ValueError("unknown spell"))
        abilities_mod = MagicMock()
        abilities_mod.get_ability = MagicMock(side_effect=ValueError("unknown ability"))
        with pytest.raises(ToolError, match="not an activatable capability"):
            await _call("not_a_real_id", spells_mod=spells_mod, abilities_mod=abilities_mod, **mods)
        for fn in fns.values():
            fn.assert_not_awaited()


class TestToolRegistration:
    def test_activate_is_a_single_strict_function_tool(self):
        assert is_function_tool(activate)
        assert not is_raw_function_tool(activate)
