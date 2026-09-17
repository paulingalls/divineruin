from unittest.mock import AsyncMock, patch

import pytest
from combat.test_hostile_ability_save import _deps, _save, _state
from combat.test_reaction_ownership_gate import _start_mocks
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_turn
import conditions
from combat_init import _start_combat_impl, class_reaction_ids
from session_data import CombatParticipant, CombatState


@pytest.mark.asyncio
@pytest.mark.parametrize("player_class", ["mage", "warrior"])
async def test_unowned_charge_is_refused_before_any_mechanical_write(player_class):
    state = _state()
    context, deps = _deps(state)
    deps["queries"].get_player.return_value["class"] = player_class

    with (
        patch("check_resolution_save.roll_participant_save", return_value=_save(False)) as save,
        patch("ability_persistence.owns_elective", AsyncMock(return_value=False)),
        patch("ability_persistence.update_player_resources", new_callable=AsyncMock) as update,
        pytest.raises(ToolError, match="Brann hasn't learned Unstoppable Charge"),
    ):
        await combat_turn._resolve_phase_impl(context, **deps)

    assert not context.userdata.combat_state.get_participant("foe").conditions
    save.assert_not_called()
    update.assert_not_awaited()
    deps["mutations"].update_player_hp.assert_not_awaited()


def test_reaction_offers_respect_level_requirement():
    assert "mage_counterspell" not in class_reaction_ids("mage", 2)
    assert "mage_counterspell" in class_reaction_ids("mage", 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(("level", "offered"), [(2, False), (3, True)])
async def test_combat_start_filters_reactions_by_player_level(level, offered):
    mutations, queries, content = _start_mocks("mage", level)
    context = make_context()

    await _start_combat_impl(
        context,
        encounter_id="empty_road",
        encounter_description="The road is quiet.",
        mutations=mutations,
        queries=queries,
        content=content,
    )

    player = context.userdata.combat_state.get_participant("player_1")
    assert ("mage_counterspell" in player.reaction_ids) is offered


def _bard_phase(level):
    bard = CombatParticipant("player_1", "Lyra", "player", 15, 20, 20, 13, level=level)
    ally = CombatParticipant("ally", "Brann", "companion", 12, 20, 20, 13)
    foe = CombatParticipant("foe", "Ogre", "enemy", 10, 20, 20, 13)
    state = CombatState(
        combat_id="mass_inspire_level",
        participants=[bard, ally, foe],
        initiative_order=["player_1", "ally", "foe"],
        beat="resolution",
        pending_declarations={
            "player_1": {"type": "ability", "action": "bard_mass_inspire", "target_ids": ["player_1", "ally"]},
        },
    )
    context, deps = _deps(state)
    deps["queries"].get_player.return_value = {
        "player_id": "player_1",
        "class": "bard",
        "level": level,
        "stamina": {"current": 0, "max": 0},
        "focus": {"current": 10, "max": 10},
    }
    return context, deps


@pytest.mark.asyncio
async def test_mass_inspire_declaration_is_refused_below_its_level():
    context, deps = _bard_phase(1)

    with (
        patch("ability_persistence.update_player_resources", new_callable=AsyncMock) as update,
        pytest.raises(ToolError, match="Lyra hasn't learned Mass Inspire"),
    ):
        await combat_turn._resolve_phase_impl(context, **deps)

    update.assert_not_awaited()
    assert not context.userdata.combat_state.get_participant("ally").conditions


@pytest.mark.asyncio
async def test_mass_inspire_declaration_lands_at_its_level():
    context, deps = _bard_phase(9)

    with patch("ability_persistence.update_player_resources", new_callable=AsyncMock) as update:
        await combat_turn._resolve_phase_impl(context, **deps)

    update.assert_awaited_once()
    ally = context.userdata.combat_state.get_participant("ally")
    assert conditions.has_condition(ally.conditions, "inspired")
