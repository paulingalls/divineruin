import json
import random
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_save
import combat_durability
import combat_hold
import event_types as E
import reaction_spend
from check_resolution_attack import AttackResult
from combat_events import EventSink
from combat_packet import _resolve_one_packet
from declarations import Declaration, DeclarationType
from tool_support import SOUND_ATTACK_HIT, SOUND_ATTACK_MISS

FIXTURE_PATH = Path(__file__).resolve().parents[4] / "packages" / "shared" / "fixtures" / "enemy_action_shapes.json"
ACTIONS = json.loads(FIXTURE_PATH.read_text())
REAL_ROLL_PARTICIPANT_SAVE = check_resolution_save.roll_participant_save


def _participant(state, participant_id):
    participant = state.get_participant(participant_id)
    assert participant is not None
    return participant


def _armor():
    return {
        "id": "plate_armor",
        "type": "armor",
        "durability_tier": "standard",
        "slot_info": {"quantity": 1, "equipped": True, "current_hits": 10},
    }


def _concentration():
    return MagicMock(
        break_concentration_on_damage=AsyncMock(return_value=None),
        break_concentration_on_incapacitation=AsyncMock(return_value=None),
    )


async def _resolve_save_damage(*, save_seed: int):
    state = _make_combat_state(player_hp=25)
    enemy = _participant(state, "goblin_scout_1")
    action = {**ACTIONS["valid_half_on_success"], "damage": "1d1+6"}
    enemy.action_pool = [action]
    declaration = Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id="player_1")
    packet = SimpleNamespace(actor_id=enemy.id, declaration=declaration)
    mutations = MagicMock(update_player_hp=AsyncMock())
    queries = MagicMock(get_player_inventory=AsyncMock(return_value=[_armor()]))
    durability_mutations = MagicMock(update_item_durability=AsyncMock())
    sink = EventSink()
    player = _participant(state, "player_1")
    save_result = REAL_ROLL_PARTICIPANT_SAVE(
        player, action["save"], action["dc"], action["name"], rng=random.Random(save_seed)
    )
    save = MagicMock(return_value=save_result)
    session = make_context().userdata

    async def accrue(*args, **kwargs):
        return await combat_durability._accrue_durability(*args, **kwargs, mutations=durability_mutations)

    with (
        patch("check_resolution_save.roll_participant_save", save),
        patch("combat_support._accrue_durability", side_effect=accrue),
    ):
        summary = await _resolve_one_packet(
            session,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=MagicMock(),
            concentration_break_mod=_concentration(),
            sink=sink,
        )
    return session, state, summary, sink, save_result, mutations, durability_mutations


@pytest.mark.parametrize(
    ("save_seed", "expected_damage", "save_success", "expected_sound", "expected_hit"),
    [
        (6, 3, True, SOUND_ATTACK_MISS, False),
        (1, 7, False, SOUND_ATTACK_HIT, True),
    ],
)
async def test_save_damage_announces_the_save_and_applied_damage(
    save_seed, expected_damage, save_success, expected_sound, expected_hit
):
    session, state, summary, sink, save, mutations, _durability_mutations = await _resolve_save_damage(
        save_seed=save_seed
    )

    assert _participant(state, "player_1").hp_current == 25 - expected_damage
    assert summary["damage"] == expected_damage
    assert summary["hit"] is expected_hit
    assert [event.event_type for event in sink.captured[:2]] == [E.DICE_ROLL, E.PLAY_SOUND]
    assert sink.captured[0].payload == {
        "roll_type": "saving_throw",
        "save_type": save.save_type,
        "roll": save.roll,
        "total": save.total,
        "success": save_success,
        "dramatic": save.dramatic,
        "context": save.context,
        "damage": expected_damage,
    }
    assert [event.payload["sound_name"] for event in sink.captured if event.event_type == E.PLAY_SOUND] == [
        expected_sound
    ]
    mutations.update_player_hp.assert_awaited_once_with("player_1", 25 - expected_damage, conn=None)
    outcome = "hit" if expected_hit else "miss"
    assert session.recent_events[-1] == f"Goblin Scout attacks Kael: {outcome}, {expected_damage} damage"


async def test_made_save_does_not_cost_armor_or_play_the_hit_sound():
    _session, _state, summary, sink, _save, _mutations, durability_mutations = await _resolve_save_damage(save_seed=6)

    assert summary["durability"] == {}
    assert summary["hit"] is False
    assert SOUND_ATTACK_HIT not in [
        event.payload["sound_name"] for event in sink.captured if event.event_type == E.PLAY_SOUND
    ]
    assert E.ITEM_DURABILITY_HIT not in [event.event_type for event in sink.captured]
    durability_mutations.update_item_durability.assert_not_awaited()


async def test_failed_save_costs_armor_after_the_announced_damage():
    _session, _state, summary, sink, _save, _mutations, durability_mutations = await _resolve_save_damage(save_seed=1)

    assert summary["durability"]["armor"]["current_hits"] == 9
    assert [event.event_type for event in sink.captured] == [E.DICE_ROLL, E.PLAY_SOUND, E.ITEM_DURABILITY_HIT]
    durability_mutations.update_item_durability.assert_awaited_once_with("player_1", "plate_armor", 9, conn=None)


async def test_held_combined_ability_wastes_before_windows_when_target_fell():
    state = _make_combat_state(player_fallen=True)
    enemy = _participant(state, "goblin_scout_1")
    enemy.action_pool = [ACTIONS["valid_combined_bite"]]
    player = _participant(state, "player_1")
    reactor = replace(player, id="player_2", name="Mira", is_fallen=False, has_reaction_ability=True)
    state.participants.append(reactor)
    state.reactions_available[reactor.id] = reaction_spend.unspent()
    state.pending_declarations[enemy.id] = {
        "type": "ability",
        "action": "Venom Bite",
        "target_id": player.id,
    }
    packet = SimpleNamespace(actor_id=enemy.id, initiative=enemy.initiative)
    state.held_actions = combat_hold.hold_enemy_packets(state, [packet])
    resolver = MagicMock()
    sink = EventSink()

    summaries = await combat_hold.pump(
        make_context().userdata,
        state,
        packet_deps={
            "resolver": resolver,
            "sink": sink,
            "mutations": MagicMock(update_player_hp=AsyncMock()),
            "queries": MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            "concentration_break_mod": _concentration(),
        },
    )

    assert summaries == [{"actor_id": enemy.id, "resolved": False, "reason": "Kael already fell"}]
    assert state.held_actions == []
    assert state.open_window is None
    resolver.resolve_attack.assert_not_called()
    assert E.DICE_ROLL not in [event.event_type for event in sink.captured]


async def test_combined_damage_preserves_a_wasted_condition_reason():
    state = _make_combat_state(player_hp=25)
    enemy = _participant(state, "goblin_scout_1")
    action = ACTIONS["valid_combined_bite"]
    enemy.action_pool = [action]
    packet = SimpleNamespace(
        actor_id=enemy.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action=action["name"], target_id="player_1"),
    )
    resolver = MagicMock()
    resolver.resolve_attack.return_value = AttackResult(
        hit=True,
        roll=15,
        attack_modifier=4,
        attack_total=19,
        target_ac=14,
        damage=4,
        damage_type="piercing",
        target_hp_remaining=21,
        target_killed=False,
        narrative_hint="",
    )

    with patch(
        "combat_enemy_action._resolve_enemy_condition_packet",
        AsyncMock(return_value={"resolved": False, "reason": "condition diagnostic"}),
    ):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            resolver=resolver,
            concentration_break_mod=_concentration(),
            sink=EventSink(),
        )

    assert _participant(state, "player_1").hp_current == 21
    assert summary["damage"] == 4
    assert summary["resolved"] is True
    assert summary["reason"] == "condition diagnostic"
