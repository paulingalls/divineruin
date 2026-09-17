"""Social reactions are offered only for the held action they can affect."""

import json
from pathlib import Path

import pytest

import combat_hold
import reaction_spend
import reaction_windows
from reaction_gate import HOLLOW_CATEGORIES, is_hollow, offered_reactions, validate_reaction_activation
from session_data import CombatParticipant, CombatState

_CONTENT = Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json"


def _participant(pid: str, *, kind: str, reactions=(), category="", attributes=None):
    return CombatParticipant(
        id=pid,
        name=pid,
        type=kind,
        initiative=10,
        hp_current=20,
        hp_max=20,
        ac=12,
        attributes=attributes or {"charisma": 12, "wisdom": 12},
        category=category,
        reaction_ids=list(reactions),
    )


def _paused(*, action_kind="attack", stage=reaction_windows.PRE_ROLL, target_id="player_1", enemy=None):
    player = _participant(
        "player_1",
        kind="player",
        reactions=("marshal_countermand", "spy_plausible_deniability", "diplomat_objection"),
    )
    actor = enemy or _participant("enemy_1", kind="enemy")
    state = CombatState(
        combat_id="social-subject",
        participants=[player, actor],
        initiative_order=[player.id, actor.id],
        beat="narration",
        reactions_available={player.id: reaction_spend.unspent()},
    )
    triggers = (
        reaction_windows.pre_roll_triggers({})
        if stage == reaction_windows.PRE_ROLL
        else reaction_windows.post_roll_triggers({}, hit=True)
    )
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=stage,
        actor_id=actor.id,
        target_id=target_id,
        action_kind=action_kind,
        triggers=triggers,
    )
    return state


def _ids(state):
    return {row["id"] for row in offered_reactions(state)}


def test_an_attack_offers_only_the_pre_roll_objection():
    assert _ids(_paused()) == {"diplomat_objection"}
    assert _ids(_paused(stage=reaction_windows.POST_ROLL)) == set()


def test_command_and_accusation_offer_only_their_subject_reactions():
    assert _ids(_paused(action_kind="command")) == {"marshal_countermand", "diplomat_objection"}
    assert _ids(_paused(action_kind="accusation")) == {
        "spy_plausible_deniability",
        "diplomat_objection",
    }


def test_the_held_action_producer_puts_the_real_kind_on_the_window():
    enemy = _participant("enemy_1", kind="enemy")
    enemy.action_pool = [{"name": "Rally", "kind": "command", "properties": []}]
    state = _paused(enemy=enemy)
    head = {
        "seq": 0,
        "actor_id": enemy.id,
        "declaration": {"type": "attack", "action": "Rally", "target_id": "player_1"},
    }

    combat_hold._open(state, head, reaction_windows.PRE_ROLL, reaction_windows.pre_roll_triggers({}))

    assert state.open_window is not None
    assert state.open_window["action_kind"] == "command"
    assert "marshal_countermand" in _ids(state)


def test_plausible_deniability_is_bound_to_the_accused():
    assert "spy_plausible_deniability" not in _ids(_paused(action_kind="accusation", target_id="bystander"))


@pytest.mark.parametrize(
    ("ability_id", "kind", "match"),
    [
        ("marshal_countermand", "attack", "command.*attack"),
        ("spy_plausible_deniability", "command", "accusation.*command"),
    ],
)
def test_activation_refuses_the_wrong_subject_and_names_both(ability_id, kind, match):
    with pytest.raises(ValueError, match=match):
        validate_reaction_activation(_paused(action_kind=kind), "player_1", ability_id)


def test_objection_refuses_post_roll_and_hollow_actors():
    with pytest.raises(ValueError, match=r"pre_roll.*post_roll"):
        validate_reaction_activation(_paused(stage=reaction_windows.POST_ROLL), "player_1", "diplomat_objection")
    hollow = _participant("hollow", kind="enemy", category="hollow_rend")
    with pytest.raises(ValueError, match="Hollow"):
        validate_reaction_activation(_paused(enemy=hollow), "player_1", "diplomat_objection")


def test_hollow_identity_is_literal_and_covers_every_authored_hollow_category():
    assert frozenset({"hollow_drift", "hollow_rend"}) == HOLLOW_CATEGORIES
    assert is_hollow(_participant("drift", kind="enemy", category="hollow_drift"))
    assert is_hollow(_participant("rend", kind="enemy", category="hollow_rend"))
    assert is_hollow(_participant("echo", kind="temporary_hollowed", category=""))
    assert not is_hollow(_participant("new", kind="enemy", category="hollow_new"))

    encounters = json.loads(_CONTENT.read_text())
    authored = {
        enemy["category"]
        for encounter in encounters
        for enemy in encounter["enemies"]
        if enemy["category"].startswith("hollow_")
    }
    assert authored == set(HOLLOW_CATEGORIES)


def test_a_window_without_an_action_kind_fails_loud():
    state = _paused()
    assert state.open_window is not None
    del state.open_window["action_kind"]
    with pytest.raises(KeyError, match="action_kind"):
        offered_reactions(state)


@pytest.mark.parametrize(
    "declaration",
    [
        {"type": "maneuver", "action": "Invented", "target_id": "player_1"},
        {"type": "attack", "action": "Invented", "target_id": "player_1"},
    ],
)
def test_an_unresolvable_targeted_action_opens_no_reaction_window(declaration):
    state = _paused()
    state.held_actions = [{"seq": 0, "actor_id": "enemy_1", "declaration": declaration}]
    assert combat_hold._opens_windows(state, state.held_actions[0]) is False
