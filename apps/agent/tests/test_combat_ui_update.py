"""Tests for the COMBAT_UI_UPDATE producer (M12, story-001).

The pure `build_combat_ui_update(state)` builder projects CombatState into the
wire packet the mobile HUD's `parseCombatant` consumes
(apps/mobile/src/audio/game-event-handler.ts:93-119). Field names and shapes
must match exactly — a drift breaks the dead-field render the M4.3 sprint
shipped (concern 76fc7caa200c).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import make_context

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


# --- shape / contract tests -------------------------------------------------


def test_packet_top_level_keys():
    """Top-level packet exposes exactly the two keys mobile reads."""
    packet = build_combat_ui_update(_state([_participant("p1")]))
    assert set(packet.keys()) == {"round", "combatants"}


def test_combatant_shape_matches_mobile_parser():
    """Each combatant entry has exactly the keys parseCombatant reads."""
    packet = build_combat_ui_update(_state([_participant("p1")]))
    expected = {"id", "name", "isAlly", "hpCurrent", "hpMax", "conditions", "isActive"}
    assert set(packet["combatants"][0].keys()) == expected


def test_packet_round_reflects_post_advance_state():
    """After advance_combat_phase WRAP -> next-round DECLARATION, the emit point
    sees round_number incremented. The packet surfaces that value verbatim
    (the round just entered, not the wrap that just completed)."""
    state = _state([_participant("p1")], round_number=3)
    packet = build_combat_ui_update(state)
    assert packet["round"] == 3


# --- is_ally: CombatParticipant property (canonical source) -----------------


def test_is_ally_property_player_companion_true_enemy_hollowed_false():
    """CombatParticipant.is_ally is the canonical ally/enemy classifier — all
    consumers (HUD producer, future role logic) read this instead of re-encoding
    the type taxonomy. Pinned here so a future type rename surfaces in one place."""
    assert _participant("p1", p_type="player").is_ally is True
    assert _participant("c1", p_type="companion").is_ally is True
    assert _participant("e1", p_type="enemy").is_ally is False
    assert _participant("th1", p_type="temporary_hollowed").is_ally is False


# --- isAlly mapping ---------------------------------------------------------


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


# --- isActive marks the next-up actor --------------------------------------


def test_isActive_marks_initiative_head_only():
    """At Beat-4 emit, the wrap has reset current_turn_index=0 — the participant
    whose id is initiative_order[0] is the next-up actor and gets isActive=True;
    every other participant is False."""
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
    """Defensive: if the emit ever runs with current_turn_index>0 (a future
    mid-round caller), only the actor at that index lights up. Pins the
    semantic so a refactor can't silently break it."""
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
    """Pre-initiative or degenerate state: no isActive flag fires."""
    state = _state(
        [_participant("p1")],
        initiative_order=[],
        current_turn_index=0,
    )
    packet = build_combat_ui_update(state)
    assert packet["combatants"][0]["isActive"] is False


def test_isActive_skips_fallen_actor_at_initiative_head():
    """An enemy at the top of initiative_order who fell last round is NOT the
    next-up actor — the HUD must highlight the next LIVE participant in the
    order. Nothing prunes initiative_order on death, so the producer must skip."""
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
    """is_dead (instant-death overkill) behaves like is_fallen for HUD purposes."""
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
    """Degenerate edge case: every participant fallen — no one is active."""
    p1 = _participant("p1", p_type="player")
    p1.is_fallen = True
    e1 = _participant("e1", p_type="enemy")
    e1.is_fallen = True
    state = _state([p1, e1], initiative_order=["p1", "e1"], current_turn_index=0)
    packet = build_combat_ui_update(state)
    for c in packet["combatants"]:
        assert c["isActive"] is False


# --- conditions projection --------------------------------------------------


def test_conditions_projected_to_type_stacks_source_only():
    """Wire packet drops duration/stage; mobile parser reads only
    {type, stacks, source}. Pinning the minimal contract prevents drift —
    extras would weaken story-002's mobile mirror."""
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
    """Defensive: a malformed condition missing 'source' emits source=''
    (matches mobile parseCondition fail-soft); the entry still survives."""
    conditions = [{"type": "stunned"}]
    state = _state([_participant("p1", conditions=conditions)])
    packet = build_combat_ui_update(state)
    emitted = packet["combatants"][0]["conditions"][0]
    assert emitted == {"type": "stunned", "stacks": 1, "source": ""}


def test_empty_conditions_list_emits_empty_list():
    state = _state([_participant("p1", conditions=[])])
    packet = build_combat_ui_update(state)
    assert packet["combatants"][0]["conditions"] == []


# --- hp + name passthrough --------------------------------------------------


def test_hp_and_name_passthrough():
    state = _state([_participant("p1", name="Kael", hp_current=12, hp_max=25)])
    c = build_combat_ui_update(state)["combatants"][0]
    assert c["name"] == "Kael"
    assert c["hpCurrent"] == 12
    assert c["hpMax"] == 25


# --- start_combat emit (M12 close-cycle fix: concern 4045481bfc3e) ---------


def _start_combat_player(stored_conditions=None):
    return {
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
    "id": "goblin_patrol",
    "name": "Goblin Patrol",
    "difficulty": "easy",
    "enemies": [
        {
            "id": "goblin_1",
            "name": "Goblin",
            "level": 1,
            "ac": 13,
            "hp": 7,
            "attributes": _START_ATTRS,
            "action_pool": [],
        },
    ],
}


@pytest.mark.asyncio
@patch("combat_init.publish_game_event", new_callable=AsyncMock)
@patch("combat_init._publish_sounds", new_callable=AsyncMock)
async def test_start_combat_emits_combat_ui_update_for_hud_init(_mock_sounds, mock_event):
    """Without an emit at combat_start, the HUD's combat-tracker stays empty for
    round 1 (COMBAT_UI_UPDATE only fired at the Beat-4 wrap before this fix).
    Resolves concern 4045481bfc3e — initial state push so icons/chips render
    from frame one, not after the first wrap."""
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(get_player=AsyncMock(return_value=_start_combat_player()))
    content = MagicMock(
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
    # Initial state: empty conditions, exactly one active actor (initiative head).
    assert all(c["conditions"] == [] for c in payload["combatants"])
    assert sum(1 for c in payload["combatants"] if c["isActive"]) == 1


@pytest.mark.asyncio
@patch("combat_init.publish_game_event", new_callable=AsyncMock)
@patch("combat_init._publish_sounds", new_callable=AsyncMock)
async def test_start_combat_ui_update_fires_after_combat_started(_mock_sounds, mock_event):
    """Event ordering: COMBAT_STARTED must reach the client before
    COMBAT_UI_UPDATE so the mobile session.setCombat(true) gate latches before
    the tracker tries to render."""
    mutations = MagicMock(save_combat_state=AsyncMock())
    queries = MagicMock(get_player=AsyncMock(return_value=_start_combat_player()))
    content = MagicMock(
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
