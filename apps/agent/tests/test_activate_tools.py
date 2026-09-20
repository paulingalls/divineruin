"""Tests for activate_tools.activate — the polymorphic Phase-5 dispatcher (M25 story-001).

activate(id) is a pure router: it resolves an id to a kind (reserved token, Veil Anchor, spell,
ability, or mentor variant) and dispatches to the matching pre-existing ``_impl``. No transaction
of its own — each target ``_impl`` still opens and commits its own. Routing is mostly proven with
injected stub impls (AsyncMock); each target ``_impl`` already has its own test suite for its own
behavior. The one exception is the variant namespace, whose id resolution is also pinned against
the real loaded catalog so mocking both sides cannot hide a content/routing drift.
"""

import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolContext, ToolError, is_function_tool, is_raw_function_tool
from sample_fixtures import make_context

import abilities
import mentor_variants
import reaction_gate
import reaction_spend
import reaction_windows
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
    context=None,
    target_id=None,
    target_ids=None,
    spells_mod=spells,
    abilities_mod=abilities,
    variants_mod=mentor_variants,
    **mods,
):
    ctx = context or make_context()
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
        abilities_mod.get_ability = MagicMock(return_value=MagicMock(spell_id=None))
        ctx, result = await _call(
            "warrior_devastating_strike", target_id="orc_1", spells_mod=spells_mod, abilities_mod=abilities_mod, **mods
        )
        assert result == "ability-result"
        fns["request_ability"].assert_awaited_once_with(
            ctx, "warrior_devastating_strike", target_id="orc_1", target_ids=None
        )

    async def test_spell_backed_ability_casts_its_spell_outside_combat(self):
        mods, fns = _mocks()
        ctx, result = await _call("mage_arcane_bolt", target_ids=["goblin_1"], **mods)

        assert result == "spell-result"
        fns["cast_spell"].assert_awaited_once_with(ctx, "arcane_bolt", target_id=None, target_ids=["goblin_1"])
        fns["request_ability"].assert_not_awaited()

    async def test_spell_backed_ability_does_not_cast_via_activate_in_combat(self):
        mods, fns = _mocks()
        ctx = make_context()
        ctx.userdata.combat_state = _make_combat_state()

        _, result = await _call("mage_arcane_bolt", context=ctx, **mods)

        assert result == "ability-result"
        fns["cast_spell"].assert_not_awaited()
        fns["request_ability"].assert_awaited_once_with(ctx, "mage_arcane_bolt", target_id=None, target_ids=None)


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


def _two_reactor_window():
    """A paused post-roll window that offers player_1 and player_2 a DIFFERENT reaction each."""
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.has_reaction_ability = True
    player.reaction_ids = ["rogue_uncanny_dodge", "rogue_slippery"]
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=reaction_windows.POST_ROLL,
        actor_id="goblin_scout_1",
        target_id="player_1",
        action_kind="attack",
        triggers=reaction_windows.post_roll_triggers({}, hit=True),
    )
    state.participants.append(dataclasses.replace(player, id="player_2", reaction_ids=["guardian_intercept"]))
    state.reactions_available = {"player_1": reaction_spend.unspent(), "player_2": reaction_spend.unspent()}
    assert [reaction["id"] for reaction in reaction_gate.offered_reactions(state)] == [
        "rogue_uncanny_dodge",
        "guardian_intercept",
    ]
    ctx = make_context(party_member_ids=["player_2"])
    ctx.userdata.combat_state = state
    return ctx


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

    async def test_unknown_id_at_an_open_window_names_the_reactions_that_would_fit(self):
        mods, fns = _mocks()
        ctx = _two_reactor_window()

        with ctx.userdata._bind_authenticated_actor("player_2", 7, lambda *_args: None):
            with pytest.raises(ToolError) as raised:
                await _activate_impl(ctx, "uncanny_dodge", **mods)

        message = str(raised.value)
        assert "not an activatable capability" in message
        assert "guardian_intercept" in message
        assert "rogue_slippery" not in message
        assert "rogue_uncanny_dodge" not in message
        for fn in fns.values():
            fn.assert_not_awaited()

    async def test_unbound_turn_at_an_open_window_still_gets_the_plain_refusal(self):
        """The hint is not a spend, so an unbound turn loses the hint, not the refusal.

        A reconnect or card-tap reply drives the DM with no authenticated speaker. Raising the
        binding's RuntimeError from here would reach the DM as livekit's "An internal error
        occurred" (llm/utils.py make_function_call_output) instead of the id it got wrong.
        """
        mods, fns = _mocks()
        ctx = _two_reactor_window()

        with pytest.raises(ToolError) as raised:
            await _activate_impl(ctx, "uncanny_dodge", **mods)

        assert str(raised.value) == "'uncanny_dodge' is not an activatable capability."
        for fn in fns.values():
            fn.assert_not_awaited()

    async def test_unknown_id_outside_combat_keeps_the_plain_refusal(self):
        mods, _fns = _mocks()
        ctx = make_context()
        ctx.userdata.combat_state = None

        with pytest.raises(ToolError) as raised:
            await _activate_impl(ctx, "uncanny_dodge", **mods)

        assert str(raised.value) == "'uncanny_dodge' is not an activatable capability."

    async def test_unknown_id_in_combat_with_no_open_window_keeps_the_plain_refusal(self):
        mods, _fns = _mocks()
        state = _make_combat_state()
        player = state.get_participant("player_1")
        assert player is not None
        player.has_reaction_ability = True
        player.reaction_ids = ["rogue_uncanny_dodge"]
        state.reactions_available = {"player_1": reaction_spend.unspent()}
        ctx = make_context()
        ctx.userdata.combat_state = state

        with pytest.raises(ToolError) as raised:
            await _activate_impl(ctx, "uncanny_dodge", **mods)

        assert str(raised.value) == "'uncanny_dodge' is not an activatable capability."


class TestToolRegistration:
    def test_activate_is_a_single_strict_function_tool(self):
        assert is_function_tool(activate)
        assert not is_raw_function_tool(activate)

    def test_activate_schema_has_no_actor_input(self):
        schema = ToolContext([activate]).parse_function_tools("anthropic", strict=True)[0]["input_schema"]

        assert set(schema["properties"]) == {"id", "target_id", "target_ids"}
