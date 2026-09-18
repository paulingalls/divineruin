import json
import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_attack
import check_resolution_save
import combat_hold
import reaction_spend
from check_resolution_attack import AttackResult
from combat_packet import _resolve_one_packet
from declarations import Declaration, DeclarationType

FIXTURE_PATH = Path(__file__).resolve().parents[4] / "packages" / "shared" / "fixtures" / "enemy_action_shapes.json"
ACTIONS = json.loads(FIXTURE_PATH.read_text())
REAL_ROLL_PARTICIPANT_SAVE = check_resolution_save.roll_participant_save


def _participant(state, participant_id):
    participant = state.get_participant(participant_id)
    assert participant is not None
    return participant


def _attack_result(*, hit: bool, damage: int = 4) -> AttackResult:
    return AttackResult(
        hit=hit,
        roll=15 if hit else 2,
        attack_modifier=4,
        attack_total=19 if hit else 6,
        target_ac=14,
        damage=damage if hit else 0,
        damage_type="piercing",
        target_hp_remaining=21 if hit else 25,
        target_killed=False,
        narrative_hint="",
    )


async def _resolve(action, *, hit=True, save_success=False, declaration_type=DeclarationType.ATTACK):
    state = _make_combat_state(player_hp=25)
    _participant(state, "goblin_scout_1").action_pool = [action]
    declaration = Declaration(type=declaration_type, action=action["name"], target_id="player_1")
    packet = SimpleNamespace(actor_id="goblin_scout_1", declaration=declaration)
    resolver = MagicMock()
    attack_seed = 0 if hit else 2
    resolver.resolve_attack.side_effect = lambda *args, **kwargs: check_resolution_attack.resolve_attack(
        *args, **kwargs, rng=random.Random(attack_seed)
    )
    save_seed = 5 if save_success else 1
    save = MagicMock(
        side_effect=lambda *args, **kwargs: REAL_ROLL_PARTICIPANT_SAVE(*args, **kwargs, rng=random.Random(save_seed))
    )
    mutations = MagicMock(update_player_hp=AsyncMock())
    queries = MagicMock(get_player_inventory=AsyncMock(return_value=[]))
    concentration = MagicMock(
        break_concentration_on_damage=AsyncMock(return_value=None),
        break_concentration_on_incapacitation=AsyncMock(return_value=None),
    )
    sink = MagicMock(emit=AsyncMock())
    with patch("check_resolution_save.roll_participant_save", save):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=concentration,
            sink=sink,
        )
    return state, summary, resolver, save


@pytest.mark.parametrize("declaration_type", [DeclarationType.ATTACK, DeclarationType.ABILITY])
async def test_combined_bite_hit_damages_then_failed_save_poisons(declaration_type):
    state, summary, resolver, save = await _resolve(ACTIONS["valid_combined_bite"], declaration_type=declaration_type)

    assert summary["damage"] > 0
    assert _participant(state, "player_1").hp_current == 25 - summary["damage"]
    assert summary["condition_inflicted"] == "poisoned"
    resolver.resolve_attack.assert_called_once()
    save.assert_called_once()


async def test_combined_bite_miss_does_neither_damage_nor_save():
    state, summary, _, save = await _resolve(ACTIONS["valid_combined_bite"], hit=False)

    assert _participant(state, "player_1").hp_current == 25
    assert summary["hit"] is False
    assert "condition_inflicted" not in summary
    save.assert_not_called()


async def test_combined_bite_made_save_keeps_damage_only():
    state, summary, _, save = await _resolve(ACTIONS["valid_combined_bite"], save_success=True)

    assert _participant(state, "player_1").hp_current == 25 - summary["damage"]
    assert summary["condition_resisted"] == "poisoned"
    assert "condition_inflicted" not in summary
    save.assert_called_once()


@pytest.mark.parametrize(("save_success", "expected_damage"), [(False, 7), (True, 3)])
async def test_save_damage_is_full_on_failure_and_floor_half_on_success(save_success, expected_damage):
    action = {**ACTIONS["valid_half_on_success"], "damage": "1d1+6"}
    state, summary, resolver, save = await _resolve(action, save_success=save_success)

    assert _participant(state, "player_1").hp_current == 25 - expected_damage
    assert summary["damage"] == expected_damage
    assert summary["damage_halved"] is save_success
    resolver.resolve_attack.assert_not_called()
    save.assert_called_once()


@pytest.mark.parametrize(
    ("save_success", "expected_damage", "condition_outcome"),
    [(True, 3, "condition_resisted"), (False, 7, "condition_inflicted")],
)
async def test_corruption_wave_uses_one_save_not_an_attack_roll(save_success, expected_damage, condition_outcome):
    action = {**ACTIONS["corruption_wave"], "damage": "1d1+6"}
    state, summary, resolver, save = await _resolve(action, save_success=save_success)

    assert _participant(state, "player_1").hp_current == 25 - expected_damage
    assert summary[condition_outcome] == "poisoned"
    resolver.resolve_attack.assert_not_called()
    save.assert_called_once()


async def test_held_combined_bite_opens_both_windows_and_rolls_with_bonuses():
    state = _make_combat_state()
    enemy = _participant(state, "goblin_scout_1")
    enemy.action_pool = [ACTIONS["valid_combined_bite"]]
    player = _participant(state, "player_1")
    player.has_reaction_ability = True
    state.reactions_available[player.id] = reaction_spend.unspent()
    state.ac_modifiers[player.id] = 2
    state.pending_declarations[enemy.id] = {
        "type": "attack",
        "action": "Venom Bite",
        "target_id": player.id,
    }
    packet = SimpleNamespace(actor_id=enemy.id, initiative=enemy.initiative)
    state.held_actions = combat_hold.hold_enemy_packets(state, [packet])
    resolver = MagicMock()
    resolver.resolve_attack.return_value = _attack_result(hit=True)
    deps = {
        "resolver": resolver,
        "sink": MagicMock(emit=AsyncMock()),
        "mutations": MagicMock(update_player_hp=AsyncMock()),
        "queries": MagicMock(get_player_inventory=AsyncMock(return_value=[])),
        "concentration_break_mod": MagicMock(
            break_concentration_on_damage=AsyncMock(return_value=None),
            break_concentration_on_incapacitation=AsyncMock(return_value=None),
        ),
    }

    await combat_hold.pump(make_context().userdata, state, packet_deps=deps)
    pre_roll_window = state.open_window
    assert pre_roll_window is not None
    assert pre_roll_window["stage"] == "pre_roll"

    held_save = MagicMock(
        return_value=REAL_ROLL_PARTICIPANT_SAVE(player, "constitution", 12, "poisoned", rng=random.Random(1))
    )
    with (
        patch("combat_hold.combat_marks.attack_bonus", return_value=2),
        patch("combat_hold.combat_reaction_effect.ac_bonus", return_value=3),
        patch("check_resolution_save.roll_participant_save", held_save),
    ):
        await combat_hold.pump(make_context().userdata, state, packet_deps=deps)
        post_roll_window = state.open_window
        assert post_roll_window is not None
        assert post_roll_window["stage"] == "post_roll"
        call = resolver.resolve_attack.call_args
        assert call.args[2] == player.ac + 2 + 3
        assert call.kwargs["attack_mod"] == enemy.attack_mod + 2
        summaries = await combat_hold.pump(make_context().userdata, state, packet_deps=deps)

    assert state.held_actions == []
    assert summaries[0]["hit"] is True
    assert summaries[0]["condition_inflicted"] == "poisoned"
    held_save.assert_called_once()
