from unittest.mock import AsyncMock, patch

import pytest
from combat.test_hostile_ability_save import _deps, _save, _state
from combat.test_reaction_ownership_gate import _start_mocks
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import combat_turn
from combat_init import _start_combat_impl, class_reaction_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("player_class", "owns_elective"),
    [("mage", False), ("warrior", False)],
)
async def test_unowned_charge_is_refused_before_any_mechanical_write(player_class, owns_elective):
    state = _state()
    context, deps = _deps(state)
    deps["queries"].get_player.return_value["class"] = player_class

    with (
        patch("check_resolution_save.roll_participant_save", return_value=_save(False)) as save,
        patch("ability_persistence.owns_elective", AsyncMock(return_value=owns_elective)),
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
