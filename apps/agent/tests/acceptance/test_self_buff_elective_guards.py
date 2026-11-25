"""Write boundaries for martial elective declarations."""

from unittest.mock import patch

from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import (
    bandit_attack,
    declare,
    enter_bandit_fight,
)
from acceptance.test_self_buff_electives import electives as electives
from acceptance.test_self_buff_electives import mock_combat_agent_factory as mock_combat_agent_factory

import ability_persistence
import check_resolution
import db_mutations
from combat_events import EventSink


async def test_unowned_precision_refuses_before_earlier_ally_writes(electives: MawlingHarness) -> None:
    actor, ally = electives.players
    foe = await enter_bandit_fight(electives)
    state = await electives.reload()
    warrior = state.get_participant(actor)
    earlier_ally = state.get_participant(ally)
    assert warrior is not None and earlier_ally is not None
    earlier_ally.initiative = warrior.initiative + 1
    await electives.persist()
    await declare(electives, weapon_attack(ally, foe, ""), weapon_attack(actor, foe, "precision_strike"))
    state_before, players_before = await electives.snapshot()
    reopened = {**state_before, "beat": "declaration", "pending_declarations": {}}
    with (
        patch.object(
            ability_persistence, "update_player_resources", wraps=ability_persistence.update_player_resources
        ) as spend,
        patch.object(db_mutations, "save_combat_state", wraps=db_mutations.save_combat_state) as save,
        patch.object(db_mutations, "update_player_hp", wraps=db_mutations.update_player_hp) as hp,
        patch.object(EventSink, "emit", autospec=True, side_effect=EventSink.emit) as emit,
        patch("check_resolution.dice_roll", wraps=check_resolution.dice_roll) as rolls,
    ):
        refusal = await electives.command("resolve_phase", {}, error=True)
    assert "hasn't learned Precision Strike" in refusal
    spend.assert_not_awaited()
    save.assert_awaited_once()
    assert save.await_args is not None and save.await_args.args[1] == reopened
    hp.assert_not_awaited()
    emit.assert_not_called()
    rolls.assert_not_called()
    assert await electives.snapshot() == (reopened, players_before)


async def test_bandit_cannot_declare_reckless_assault(electives: MawlingHarness) -> None:
    foe = await enter_bandit_fight(electives)
    strike = await bandit_attack(electives, foe, electives.players[0])
    result = await electives.command(
        "declare_phase", {"declarations": [{**strike, "rider": "reckless_assault"}]}, error=True
    )
    assert "hasn't learned Reckless Assault" in result
