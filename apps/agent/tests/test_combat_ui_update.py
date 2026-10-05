"""The mobile HUD consumes this packet, so Python field names must match its parser."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import load_test_creature, make_context

import event_types as E
from combat_init import _start_combat_impl
from combat_ui_update import build_combat_ui_update
from session_data import CombatParticipant, CombatState

_START_ATTRS = {
    "strength": 14,
    "dexterity": 12,
    "constitution": 13,
    "intelligence": 10,
    "wisdom": 11,
    "charisma": 8,
}


def _participant(
    pid: str,
    *,
    name: str | None = None,
    p_type: str = "player",
    hp_current: int = 25,
    hp_max: int = 25,
    initiative: int = 10,
    conditions: list[dict] | None = None,
) -> CombatParticipant:
    return CombatParticipant(
        id=pid,
        name=name or pid,
        type=p_type,
        initiative=initiative,
        hp_current=hp_current,
        hp_max=hp_max,
        ac=14,
        conditions=conditions or [],
    )


def _state(
    participants: list[CombatParticipant],
    *,
    beat: str = "declaration",
    round_number: int = 2,
    current_turn_index: int = 0,
    initiative_order: list[str] | None = None,
) -> CombatState:
    return CombatState(
        combat_id="c1",
        participants=participants,
        initiative_order=initiative_order if initiative_order is not None else [p.id for p in participants],
        round_number=round_number,
        current_turn_index=current_turn_index,
        beat=beat,
    )


def test_packet_top_level_keys():
    packet = build_combat_ui_update(_state([_participant("p1")]))
    assert set(packet.keys()) == {"round", "combatants"}


def test_combatant_shape_matches_mobile_parser():
    packet = build_combat_ui_update(_state([_participant("p1")]))
    expected = {"id", "name", "isAlly", "hpCurrent", "hpMax", "conditions", "isActive"}
    assert set(packet["combatants"][0].keys()) == expected


def test_packet_round_reflects_post_advance_state():
    state = _state([_participant("p1")], round_number=3)
    packet = build_combat_ui_update(state)
    assert packet["round"] == 3


def test_is_ally_property_player_companion_true_enemy_hollowed_false():
    assert _participant("p1", p_type="player").is_ally is True
    assert _participant("c1", p_type="companion").is_ally is True
    assert _participant("e1", p_type="enemy").is_ally is False
    assert _participant("th1", p_type="temporary_hollowed").is_ally is False


def test_isAlly_true_for_player_and_companion():
    state = _state(
        [
            _participant("p1", p_type="player"),
            _participant("c1", p_type="companion"),
        ]
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["p1"]["isAlly"] is True
    assert by_id["c1"]["isAlly"] is True


def test_isAlly_false_for_enemy_and_temporary_hollowed():
    state = _state(
        [
            _participant("e1", p_type="enemy"),
            _participant("th1", p_type="temporary_hollowed"),
        ]
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["e1"]["isAlly"] is False
    assert by_id["th1"]["isAlly"] is False


def test_isActive_marks_initiative_head_only():
    state = _state(
        [
            _participant("p1", p_type="player", initiative=15),
            _participant("e1", p_type="enemy", initiative=12),
            _participant("e2", p_type="enemy", initiative=8),
        ],
        initiative_order=["p1", "e1", "e2"],
        current_turn_index=0,
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["p1"]["isActive"] is True
    assert by_id["e1"]["isActive"] is False
    assert by_id["e2"]["isActive"] is False


def test_isActive_handles_mid_round_index():
    state = _state(
        [
            _participant("p1", p_type="player"),
            _participant("e1", p_type="enemy"),
        ],
        initiative_order=["p1", "e1"],
        current_turn_index=1,
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["p1"]["isActive"] is False
    assert by_id["e1"]["isActive"] is True


def test_isActive_all_false_when_initiative_order_empty():
    state = _state(
        [_participant("p1")],
        initiative_order=[],
        current_turn_index=0,
    )
    packet = build_combat_ui_update(state)
    assert packet["combatants"][0]["isActive"] is False


def test_isActive_skips_fallen_actor_at_initiative_head():
    """Do not prune a fallen participant from the authoritative roster."""
    p1 = _participant("p1", p_type="player", initiative=10)
    e1 = _participant("e1", p_type="enemy", initiative=20)
    e1.is_fallen = True  # fell last phase
    e2 = _participant("e2", p_type="enemy", initiative=15)
    state = _state(
        [e1, p1, e2],
        initiative_order=["e1", "e2", "p1"],
        current_turn_index=0,
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["e1"]["isActive"] is False, "fallen actor must NOT be marked isActive"
    assert by_id["e2"]["isActive"] is True, "next live actor in order should be active"
    assert by_id["p1"]["isActive"] is False


def test_isActive_skips_dead_actor_at_initiative_head():
    p1 = _participant("p1", p_type="player", initiative=10)
    e1 = _participant("e1", p_type="enemy", initiative=20)
    e1.is_dead = True
    state = _state(
        [e1, p1],
        initiative_order=["e1", "p1"],
        current_turn_index=0,
    )
    packet = build_combat_ui_update(state)
    by_id = {c["id"]: c for c in packet["combatants"]}
    assert by_id["e1"]["isActive"] is False
    assert by_id["p1"]["isActive"] is True


def test_isActive_all_false_when_every_actor_is_down():
    p1 = _participant("p1", p_type="player")
    p1.is_fallen = True
    e1 = _participant("e1", p_type="enemy")
    e1.is_fallen = True
    state = _state([p1, e1], initiative_order=["p1", "e1"], current_turn_index=0)
    packet = build_combat_ui_update(state)
    for c in packet["combatants"]:
        assert c["isActive"] is False


def test_conditions_projected_to_type_stacks_source_only():
    conditions = [
        {"type": "blessed", "duration": 3, "source": "divine_bless", "stacks": 1},
    ]
    state = _state([_participant("p1", conditions=conditions)])
    packet = build_combat_ui_update(state)
    emitted = packet["combatants"][0]["conditions"][0]
    assert emitted == {"type": "blessed", "stacks": 1, "source": "divine_bless"}


def test_conditions_default_stacks_when_missing():
    """Hollowed-shaped condition (conditions.py:326) omits 'stacks'; the
    builder defaults to 1 — mirrors mobile parseCondition's fail-soft."""
    conditions = [{"type": "hollowed", "duration": -1, "source": "death", "stage": 1}]
    state = _state([_participant("p1", conditions=conditions)])
    packet = build_combat_ui_update(state)
    emitted = packet["combatants"][0]["conditions"][0]
    assert emitted == {"type": "hollowed", "stacks": 1, "source": "death"}


def test_conditions_default_source_when_missing():
    conditions = [{"type": "stunned"}]
    state = _state([_participant("p1", conditions=conditions)])
    packet = build_combat_ui_update(state)
    emitted = packet["combatants"][0]["conditions"][0]
    assert emitted == {"type": "stunned", "stacks": 1, "source": ""}


def test_empty_conditions_list_emits_empty_list():
    state = _state([_participant("p1", conditions=[])])
    packet = build_combat_ui_update(state)
    assert packet["combatants"][0]["conditions"] == []


def test_hp_and_name_passthrough():
    state = _state([_participant("p1", name="Kael", hp_current=12, hp_max=25)])
    c = build_combat_ui_update(state)["combatants"][0]
    assert c["name"] == "Kael"
    assert c["hpCurrent"] == 12
    assert c["hpMax"] == 25


def _start_combat_player(stored_conditions=None):
    return {
        "speed": 30,
        "player_id": "player_1",
        "name": "Kael",
        "class": "warrior",
        "level": 5,
        "attributes": dict(_START_ATTRS),
        "hp": {"current": 25, "max": 25},
        "ac": 14,
        "skill_tiers": {},
        "conditions": stored_conditions if stored_conditions is not None else [],
    }


_START_ENCOUNTER = {
    "scene_placement": {
        "party_start": {"x": 0, "y": 0, "z": 0},
        "companion_start": {"x": 0, "y": 5, "z": 0},
        "actors": {"goblin_1": {"x": 20, "y": 0, "z": 0}},
        "locations": {},
        "zones": {},
    },
    "recommended_party_level": 1,
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "difficulty": "easy",
    "enemies": [{"id": "goblin_1", "creature_id": "fixture_goblin", "role": "standard"}],
}


@pytest.mark.asyncio
@patch("combat_init.publish_game_event", new_callable=AsyncMock)
@patch("combat_init._publish_sounds", new_callable=AsyncMock)
async def test_start_combat_emits_combat_ui_update_for_hud_init(_mock_sounds, mock_event):
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value=_start_combat_player()),
        get_player_inventory=AsyncMock(return_value=[]),
    )
    content = MagicMock(
        load_creature_enemy=load_test_creature,
        get_encounter_template=AsyncMock(return_value=_START_ENCOUNTER),
        get_npc=AsyncMock(return_value=None),
    )
    ctx = make_context()
    await _start_combat_impl(
        ctx,
        encounter_id="goblin_patrol",
        encounter_description="Goblins attack.",
        mutations=mutations,
        queries=queries,
        content=content,
    )

    ui_calls = [c for c in mock_event.call_args_list if c[0][1] == E.COMBAT_UI_UPDATE]
    assert len(ui_calls) == 1, (
        f"expected exactly one COMBAT_UI_UPDATE at combat-start, got {[c[0][1] for c in mock_event.call_args_list]}"
    )
    payload = ui_calls[0][0][2]
    assert payload["round"] == 1
    by_id = {c["id"]: c for c in payload["combatants"]}
    assert "player_1" in by_id and "goblin_1" in by_id
    assert all(c["conditions"] == [] for c in payload["combatants"])
    assert sum(1 for c in payload["combatants"] if c["isActive"]) == 1


@pytest.mark.asyncio
@patch("combat_init.publish_game_event", new_callable=AsyncMock)
@patch("combat_init._publish_sounds", new_callable=AsyncMock)
async def test_start_combat_ui_update_fires_after_combat_started(_mock_sounds, mock_event):
    """The client latches the initial HUD state, so publish it in order."""
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(
        get_player=AsyncMock(return_value=_start_combat_player()),
        get_player_inventory=AsyncMock(return_value=[]),
    )
    content = MagicMock(
        load_creature_enemy=load_test_creature,
        get_encounter_template=AsyncMock(return_value=_START_ENCOUNTER),
        get_npc=AsyncMock(return_value=None),
    )
    await _start_combat_impl(
        make_context(),
        encounter_id="goblin_patrol",
        encounter_description="Goblins attack.",
        mutations=mutations,
        queries=queries,
        content=content,
    )
    types = [c[0][1] for c in mock_event.call_args_list]
    assert types.index(E.COMBAT_STARTED) < types.index(E.COMBAT_UI_UPDATE)
