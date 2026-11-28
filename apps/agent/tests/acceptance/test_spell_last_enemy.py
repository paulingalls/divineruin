"""Dramatic attack receipts through the registered combat commands."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _dice_events, _enemy
from acceptance.merchant_harness import stock
from acceptance.seeds import seed_player_with_pools, seed_warrior_owning_base
from sample_fixtures import make_mock_room
from voice_condition_fixtures import participant

import db
import db_content_queries
import db_mutations
from activate_tools import activate
from combat_structures import add_wall
from combat_turn import declare_phase, resolve_phase
from equipment_rules import loadout_entry
from session_data import CombatParticipant, CombatState, SessionData

BOLT = "arcane_bolt"
CLEAVE = "warrior_cleaving_blow"


def _ability(actor: str, action: str, *targets: str) -> dict:
    return {**defend(actor), "kind": "ability", "action": action, "targets": list(targets)}


def _session(state: CombatState, room: MagicMock) -> SessionData:
    return SessionData(
        player_id=state.initiative_order[0], location_id=state.location_id, combat_state=state, room=room
    )


async def _saved(combat_id: str) -> CombatState:
    state = await db_mutations.load_combat_state(combat_id)
    assert state is not None
    return state


async def _start(
    state: CombatState, *, held: bool, cleave: bool = False
) -> tuple[Callable[..., Awaitable[Any]], MagicMock]:
    actor = state.initiative_order[0]
    pool = await db.get_pool()
    if cleave:
        await seed_warrior_owning_base(pool, actor, CLEAVE)
    else:
        await seed_player_with_pools(pool, player_id=actor, class_="mage", known_spells=(BOLT,))
    item_id = "dagger_balanced"
    item = await db_content_queries.get_item(item_id)
    assert item is not None
    slot, weapon, proficient = loadout_entry(item_id, item, "warrior" if cleave else "mage")
    assert proficient
    await stock(actor, item_id, 1, equipped=True)
    await pool.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
        actor,
        json.dumps({"equipment": {slot: weapon}}),
    )
    if held:
        await pool.execute(
            "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
            actor,
            '{"divine_favor":{"patron":"zhael","level":40,"max":100}}',
        )
    player = participant(state, actor)
    player.action_pool = [weapon]
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    room = make_mock_room()
    call = game_tools(_session(state, room), declare_phase, resolve_phase, activate)
    return call, room


def _attack_events(room: MagicMock) -> list[dict]:
    # Every other participant defends, so the stream's attack events all belong to the actor.
    return [event for event in _dice_events(room) if event["roll_type"] == "attack"]


def _receipt(result: dict, actor: str) -> dict:
    (packet,) = [packet for packet in result["packets"] if packet["actor_id"] == actor]
    return packet


def _label(payload: dict) -> tuple[bool, str]:
    return payload["dramatic"], payload["context"]


def _foes(hp: int, roster: str) -> list[CombatParticipant]:
    foes = [_enemy("target", hp)]
    if roster == "two":
        foes.append(_enemy("other", 100))
    elif roster == "mixed":
        foes.extend(
            [
                replace(_enemy("fallen", 0), is_fallen=True),
                replace(_enemy("ally", 30), type="companion"),
                replace(_enemy("echo", 30), type="temporary_hollowed"),
            ]
        )
    return foes


async def _single_attack(
    action: str, face: int, lethal: bool, opening: bool, held: bool, roster: str
) -> tuple[tuple[bool, str], tuple[bool, str]]:
    hp = 1 if lethal else 100
    actor = f"last_enemy_{action}_{uuid4().hex}"
    state = _build_state(actor, actor, _foes(hp, roster), first_attack_resolved=not opening)
    if roster == "mixed":
        add_wall(state, "wall", "Wall", {"x": 40, "y": -5, "z": 0}, {"x": 40, "y": 5, "z": 0})
    call, room = await _start(state, held=held)
    declaration = _ability(actor, BOLT, "target") if action == "spell" else attack(actor, "target", "Balanced Dagger")
    await call(
        "declare_phase",
        declarations=[
            declaration,
            *(defend(p.id) for p in state.participants[1:] if not p.is_fallen and not p.is_structure),
        ],
    )
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await call("resolve_phase")
        if held:
            assert result["fate_offer"]["roller_id"] == actor
            assert result["fate_offer"]["die"] == face
            assert not _attack_events(room)
            saved = await _saved(state.combat_id)
            assert participant(saved, "target").hp_current == hp
            resumed = game_tools(_session(saved, room), resolve_phase)
            result = await resumed("resolve_phase")
    packet = _receipt(result, actor)
    receipt = packet["cast"]["damage_result"] if action == "spell" else packet
    (event,) = _attack_events(room)
    assert receipt["roll"] == event["roll"] == face
    assert receipt["critical"] is event["critical"] is (face == 20)
    assert receipt["hit"] and event["success"] and receipt["damage"] == event["damage"] > 0
    assert receipt["target_fallen"] is lethal
    if lethal:
        _, ended = await call("resolve_phase")
        assert ended["outcome"] == "victory"
    else:
        saved = await _saved(state.combat_id)
        assert participant(saved, "target").hp_current == hp - receipt["damage"]
        if opening:
            assert saved.first_attack_resolved
    return _label(receipt), _label(event)


@pytest.mark.parametrize(
    ("face", "lethal", "opening", "held", "roster", "expected"),
    [
        (15, False, False, False, "single", "last_enemy"),
        (15, True, False, False, "single", "killing_blow"),
        (20, False, False, False, "single", "natural_20"),
        (20, True, False, False, "single", "natural_20"),
        (15, False, True, False, "single", "first_attack"),
        (15, False, False, True, "single", "last_enemy"),
        (15, False, True, True, "single", "first_attack"),
        (15, False, False, False, "mixed", "last_enemy"),
        (15, False, False, False, "two", ""),
    ],
    ids=["survivor", "lethal", "crit", "lethal-crit", "opener", "reloaded", "reloaded-opener", "mixed", "two-enemies"],
)
async def test_spell_and_weapon_share_dramatic_label(
    reset_db_pool: str, face: int, lethal: bool, opening: bool, held: bool, roster: str, expected: str
) -> None:
    weapon = await _single_attack("weapon", face, lethal, opening, held, roster)
    spell = await _single_attack("spell", face, lethal, opening, held, roster)
    label = bool(expected), expected
    assert weapon == spell == (label, label)


@pytest.mark.parametrize("held", [False, True], ids=["immediate", "reloaded"])
async def test_cleave_counts_after_each_swing(reset_db_pool: str, held: bool) -> None:
    actor = f"last_enemy_cleave_{uuid4().hex}"
    targets = ["first", "second"]
    state = _build_state(actor, actor, [_enemy("first", 1), _enemy("second", 100)], first_attack_resolved=True)
    call, room = await _start(state, held=held, cleave=True)
    await call("declare_phase", declarations=[_ability(actor, CLEAVE, *targets), *(defend(pid) for pid in targets)])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(16)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await call("resolve_phase")
        if held:
            first_offer = result["fate_offer"]
            assert first_offer["roller_id"] == actor and first_offer["die"] == 15
            assert not _attack_events(room)
            result = await call("activate", id="zhael_fates_thread", offer_id=first_offer["offer_id"], keep="original")
            assert result["fate_offer"]["roller_id"] == actor and result["fate_offer"]["die"] == 15
            (first_event,) = _attack_events(room)
            assert _label(first_event) == (True, "killing_blow")
            saved = await _saved(state.combat_id)
            assert participant(saved, "first").is_fallen
            assert participant(saved, "second").hp_current == 100
            resumed = game_tools(_session(saved, room), resolve_phase)
            result = await resumed("resolve_phase")
    swings = _receipt(result, actor)["attacks"]
    assert [swing["target_id"] for swing in swings] == targets
    assert [swing["target_fallen"] for swing in swings] == [True, False]
    events = _attack_events(room)
    assert [event["roll"] for event in events] == [swing["roll"] for swing in swings] == [15, 15]
    assert [event["damage"] for event in events] == [swing["damage"] for swing in swings]
    assert all(swing["damage"] > 0 for swing in swings)
    expected = [(True, "killing_blow"), (True, "last_enemy")]
    assert [_label(event) for event in events] == [_label(swing) for swing in swings] == expected
