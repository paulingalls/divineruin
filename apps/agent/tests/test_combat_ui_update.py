"""Tests for the COMBAT_UI_UPDATE producer (M12, story-001).

The pure `build_combat_ui_update(state)` builder projects CombatState into the
wire packet the mobile HUD's `parseCombatant` consumes
(apps/mobile/src/audio/game-event-handler.ts:93-119). Field names and shapes
must match exactly — a drift breaks the dead-field render the M4.3 sprint
shipped (concern 76fc7caa200c).
"""

from combat_ui_update import build_combat_ui_update
from session_data import CombatParticipant, CombatState


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
    """Top-level packet exposes exactly the three keys mobile reads."""
    packet = build_combat_ui_update(_state([_participant("p1")]))
    assert set(packet.keys()) == {"phase", "round", "combatants"}


def test_combatant_shape_matches_mobile_parser():
    """Each combatant entry has exactly the keys parseCombatant reads."""
    packet = build_combat_ui_update(_state([_participant("p1")]))
    expected = {"id", "name", "isAlly", "hpCurrent", "hpMax", "conditions", "isActive"}
    assert set(packet["combatants"][0].keys()) == expected


def test_packet_phase_round_reflect_post_advance_state():
    """After advance_combat_phase WRAP -> next-round DECLARATION, the emit point
    sees beat='declaration' and round_number incremented. The packet must
    surface those values verbatim (not the wrap-beat-that-just-completed)."""
    state = _state([_participant("p1")], beat="declaration", round_number=3)
    packet = build_combat_ui_update(state)
    assert packet["phase"] == "declaration"
    assert packet["round"] == 3


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
