"""story-004: combat sources the companion's stat block from the companions.json profile
(companion_scaling: level scaler + action_pool translator), NOT from npcs.json get_npc, and the
block is INDEPENDENT of the relationship inputs (session_count/affinity). Combat is never gated
by relationship (spec L871, the negative invariant)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from handoff._helpers import make_context as _make_context
from livekit.agents.llm import ToolError
from sample_fixtures import SAMPLE_ENCOUNTER, SAMPLE_PLAYER

from companion_profiles import get_companion_profile
from companion_scaling import (
    companion_attacks_to_action_pool,
    scale_companion_stats_to_player_level,
)
from session_data import CompanionState


def _mocks():
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
    content = MagicMock()
    content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)
    content.get_npc = AsyncMock(return_value=None)
    return mutations, queries, content


async def _run_combat_with_companion(companion: CompanionState):
    """Drive _start_combat_impl with the given companion present; return its CombatParticipant
    and the content mock (so callers can assert get_npc was never consulted)."""
    from combat_init import _start_combat_impl

    mutations, queries, content = _mocks()
    ctx = _make_context()
    ctx.userdata.companion = companion
    await _start_combat_impl(
        ctx,
        encounter_id="wolf_pack",
        encounter_description="Wolves!",
        mutations=mutations,
        queries=queries,
        content=content,
    )
    comp = next(p for p in ctx.userdata.combat_state.participants if p.type == "companion")
    return comp, content


class TestCompanionCombatProfile:
    @pytest.mark.asyncio
    async def test_companion_stats_come_from_profile_not_npcs(self):
        comp, content = await _run_combat_with_companion(CompanionState(id="companion_kael", name="Kael"))

        profile = get_companion_profile("companion_kael")
        scaled = scale_companion_stats_to_player_level(profile, SAMPLE_PLAYER["hp"]["max"], SAMPLE_PLAYER["level"])

        assert comp.hp_max == scaled.hp
        assert comp.hp_current == scaled.hp
        assert comp.ac == scaled.ac
        assert comp.level == scaled.level
        assert comp.attributes == scaled.attributes
        assert comp.action_pool == companion_attacks_to_action_pool(profile)
        # Sourced from companions.json — the legacy npcs.json get_npc path is never consulted.
        content.get_npc.assert_not_called()

    @pytest.mark.asyncio
    async def test_action_pool_is_mechanical_dice_notation(self):
        comp, _ = await _run_combat_with_companion(CompanionState(id="companion_kael", name="Kael"))
        longsword = next(a for a in comp.action_pool if a["name"] == "Longsword")
        # Narrative "1d8+STR" became plain dice the resolver can roll; attributes supply the mod.
        assert longsword["damage"] == "1d8"
        assert "STR" not in longsword["damage"]

    @pytest.mark.asyncio
    async def test_lira_arcane_bolt_resolves_hit_on_int_not_dex(self):
        # Debt 785f7399 / story-008: Lira's ranged INT Arcane Bolt must resolve its hit on INT, not
        # the ranged-default DEX. The translated action carries governing_attribute=intelligence,
        # and attack_modifier honors it — observable because Lira's INT and DEX modifiers differ.
        from check_resolution import attack_modifier
        from rules_engine import attribute_modifier, proficiency_bonus

        comp, _ = await _run_combat_with_companion(CompanionState(id="companion_lira", name="Lira"))
        bolt = next(a for a in comp.action_pool if a["name"] == "Arcane Bolt")
        assert bolt["governing_attribute"] == "intelligence"
        assert bolt.get("ranged") is True  # still ranged, but the hit stat is INT

        attacker = {"attributes": comp.attributes, "level": comp.level}
        prof = proficiency_bonus(comp.level)
        int_based = attribute_modifier(comp.attributes["intelligence"]) + prof
        dex_based = attribute_modifier(comp.attributes["dexterity"]) + prof
        assert int_based != dex_based  # the INT-vs-DEX choice is observable for Lira
        assert attack_modifier(attacker, bolt) == int_based

    @pytest.mark.asyncio
    async def test_unknown_companion_id_raises_tool_error(self):
        # A stale/unknown companion id surfaces as a ToolError (the DM-narratable not-found
        # convention), not a raw ValueError that crashes combat init.
        with pytest.raises(ToolError):
            await _run_combat_with_companion(CompanionState(id="companion_ghost", name="Ghost"))

    @pytest.mark.asyncio
    async def test_corrupt_companion_attack_raises_tool_error(self, monkeypatch):
        # A companion whose profile LOADS but carries a malformed attack (damage with no dice
        # term) makes companion_attacks_to_action_pool raise ValueError mid-init. That must
        # surface as the same DM-narratable ToolError as the unknown-id path, not a raw
        # ValueError that crashes combat init (retro-try combat-init-wrap, decision 4c60aefd).
        import dataclasses

        import combat_init
        from companion_profiles import CompanionAttack

        good = get_companion_profile("companion_kael")
        bad_attack = CompanionAttack(
            name="Broken",
            type="melee",
            reach="5 ft",
            hit="STR+prof",
            damage="STR",  # no dice/int term survives stripping -> ValueError on translate
            damage_type="slashing",
        )
        corrupt = dataclasses.replace(good, attacks=(bad_attack,))
        monkeypatch.setattr(combat_init, "get_companion_profile", lambda _: corrupt)

        with pytest.raises(ToolError):
            await _run_combat_with_companion(CompanionState(id="companion_kael", name="Kael"))

    @pytest.mark.asyncio
    async def test_combat_stat_block_independent_of_relationship(self):
        # Identical companions differing ONLY in the relationship inputs (session_count/affinity).
        early = CompanionState(id="companion_kael", name="Kael", session_count=0, affinity=0)
        bonded = CompanionState(id="companion_kael", name="Kael", session_count=50, affinity=100)
        comp_early, _ = await _run_combat_with_companion(early)
        comp_bonded, _ = await _run_combat_with_companion(bonded)

        assert comp_early.hp_max == comp_bonded.hp_max
        assert comp_early.ac == comp_bonded.ac
        assert comp_early.level == comp_bonded.level
        assert comp_early.attributes == comp_bonded.attributes
        assert comp_early.action_pool == comp_bonded.action_pool
