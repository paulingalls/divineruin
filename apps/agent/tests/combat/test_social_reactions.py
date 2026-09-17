"""Contested social reactions change the held enemy action exactly once."""

import json
from pathlib import Path

import pytest
from combat._helpers import _ac_sensitive_resolver, _damage_resolver, _resolve_deps
from sample_fixtures import make_context

import combat_hold
import combat_reaction_effect
import reaction_spend
import reaction_windows
from combat_prompts import COMBAT_PROMPT
from encounter_actions import validate_encounter_actions
from session_data import CombatParticipant, CombatState

_CONTENT = Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json"
_ENCOUNTERS = json.loads(_CONTENT.read_text())


def _ashmark_patrol():
    return next(encounter for encounter in _ENCOUNTERS if encounter["id"] == "ashmark_patrol")


def test_the_sergeant_is_the_single_valid_accusation_producer():
    carriers = [
        (encounter["id"], enemy["id"], action)
        for encounter in _ENCOUNTERS
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action.get("kind") == "accusation"
    ]
    assert carriers == [
        (
            "ashmark_patrol",
            "ashmark_sergeant",
            {
                "name": "Accusation",
                "kind": "accusation",
                "properties": [],
                "description": "Names the accused and directs the patrol's focus fire",
            },
        )
    ]
    validate_encounter_actions(_ashmark_patrol()["enemies"])


@pytest.mark.parametrize("field", ["damage", "damage_type", "applies_condition"])
def test_an_accusation_carrying_a_strike_field_is_refused(field):
    accusation = {"name": "Accusation", "kind": "accusation", field: "x"}
    with pytest.raises(ValueError, match=field):
        validate_encounter_actions([{"id": "e1", "action_pool": [accusation]}])


class SequenceRng:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def randint(self, low, high):
        self.calls.append((low, high))
        return next(self.values)


class RefusingRng:
    def randint(self, low, high):
        raise AssertionError("a stored contest must not roll again")


def _participant(pid, *, kind, initiative=10, actions=(), charisma=12, wisdom=12, ac=14):
    return CombatParticipant(
        id=pid,
        name=pid,
        type=kind,
        initiative=initiative,
        hp_current=25,
        hp_max=25,
        ac=ac,
        attributes={"strength": 12, "dexterity": 12, "charisma": charisma, "wisdom": wisdom},
        action_pool=list(actions),
    )


def _social_state(ability_id, action, *, target_id="player_1", with_striker=False):
    player = _participant("player_1", kind="player", initiative=20, charisma=16, wisdom=14)
    enemy = _participant("enemy_1", kind="enemy", initiative=15, actions=[action], charisma=12, wisdom=16)
    participants = [player, enemy]
    held = [
        {
            "seq": 0,
            "actor_id": enemy.id,
            "initiative": enemy.initiative,
            "declaration": {"type": "attack", "action": action["name"], "target_id": target_id},
            "roll": None,
            "roll_published": False,
            "opened": [reaction_windows.PRE_ROLL],
        }
    ]
    if with_striker:
        strike = {"name": "Mace", "damage": "1", "damage_type": "bludgeoning", "properties": []}
        striker = _participant("bandmate", kind="enemy", initiative=10, actions=[strike])
        participants.append(striker)
        held.append(
            {
                "seq": 1,
                "actor_id": striker.id,
                "initiative": striker.initiative,
                "declaration": {"type": "attack", "action": "Mace", "target_id": target_id},
                "roll": None,
                "roll_published": False,
                "opened": [],
            }
        )
    state = CombatState(
        combat_id="social-contest",
        participants=participants,
        initiative_order=[row.id for row in participants],
        beat="narration",
        held_actions=held,
    )
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=reaction_windows.PRE_ROLL,
        actor_id=enemy.id,
        target_id=target_id,
        action_kind=action["kind"],
        triggers=reaction_windows.pre_roll_triggers(action),
    )
    state.reactions_available = {player.id: reaction_spend.spend(ability_id, state.open_window, held_seq=0)}
    return state


def _close(state, rng):
    assert state.open_window is not None
    return combat_reaction_effect.close(
        state,
        state.held_actions[0],
        state.open_window,
        attack_action=combat_hold._attack_action(state, state.held_actions[0]),
        contest_rng=rng,
    )


def _packet_deps(resolver):
    deps = _resolve_deps()
    deps.pop("db_mod")
    deps["resolver"] = resolver
    return deps


@pytest.mark.parametrize(
    ("ability_id", "action", "effect", "opposer_total"),
    [
        (
            "marshal_countermand",
            {"name": "Rally", "kind": "command", "properties": []},
            "command_countered",
            9,  # commander CHA 12
        ),
        (
            "spy_plausible_deniability",
            {"name": "Accusation", "kind": "accusation", "properties": []},
            "accusation_dismissed",
            11,  # accuser WIS 16
        ),
    ],
)
def test_social_contest_wins_report_totals_and_persist_once(ability_id, action, effect, opposer_total):
    state = _social_state(ability_id, action)
    rng = SequenceRng([10, 8])

    packet = _close(state, rng)

    assert rng.calls == [(1, 20), (1, 20)]
    assert packet is not None
    assert packet["mechanical_effect"] == effect
    assert (packet["reactor_total"], packet["opposer_total"]) == (13, opposer_total)
    stored = state.held_actions[0]["reaction_contest"]
    assert stored == {
        "ability_id": ability_id,
        "reactor_total": 13,
        "opposer_total": opposer_total,
        "success": True,
    }

    reloaded = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    repeated = _close(reloaded, RefusingRng())
    assert repeated == packet


def test_a_tied_countermand_loses_and_malformed_stored_results_fail_loud():
    state = _social_state("marshal_countermand", {"name": "Rally", "kind": "command", "properties": []})
    packet = _close(state, SequenceRng([8, 10]))
    assert packet is not None
    assert (packet["reactor_total"], packet["opposer_total"], packet["mechanical_effect"]) == (11, 11, None)

    state.held_actions[0]["reaction_contest"] = {"ability_id": "diplomat_objection"}
    with pytest.raises(ValueError, match="stored reaction contest"):
        _close(state, RefusingRng())


def test_a_missing_contest_attribute_fails_loud():
    state = _social_state("marshal_countermand", {"name": "Rally", "kind": "command", "properties": []})
    player = state.get_participant("player_1")
    assert player is not None
    del player.attributes["charisma"]
    with pytest.raises(ValueError, match=r"player_1.*charisma"):
        _close(state, SequenceRng([10, 8]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ability_id", "action", "won", "effect", "hit"),
    [
        (
            "marshal_countermand",
            {"name": "Rally", "kind": "command", "properties": []},
            True,
            "command_countered",
            False,
        ),
        (
            "marshal_countermand",
            {"name": "Rally", "kind": "command", "properties": []},
            False,
            None,
            True,
        ),
        (
            "spy_plausible_deniability",
            {"name": "Accusation", "kind": "accusation", "properties": []},
            True,
            "accusation_dismissed",
            False,
        ),
        (
            "spy_plausible_deniability",
            {"name": "Accusation", "kind": "accusation", "properties": []},
            False,
            None,
            True,
        ),
    ],
)
async def test_mark_contests_change_the_bandmates_ac_minus_one_attack(ability_id, action, won, effect, hit):
    state = _social_state(ability_id, action, with_striker=True)
    session = make_context().userdata
    session.combat_state = state
    rng = SequenceRng([10, 8] if won else [5, 10])
    deps = _packet_deps(_ac_sensitive_resolver(attack_total=13, damage=1))

    packets = await combat_hold.pump(session, state, packet_deps=deps, contest_rng=rng)

    reaction = next(row for row in packets if row.get("declaration_type") == "reaction")
    strike = next(row for row in packets if row["actor_id"] == "bandmate")
    assert reaction["mechanical_effect"] == effect
    assert (strike["hit"], strike["attack_total"]) == (hit, 15 if hit else 13)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("won", "effect", "damage", "totals"),
    [(True, "action_hesitated", 0, (13, 11)), (False, None, 4, (8, 13))],  # diplomat CHA 16 vs actor WIS 16
)
async def test_objection_win_pops_the_attack_and_loss_allows_it(won, effect, damage, totals):
    action = {"name": "Mace", "damage": "1d6", "damage_type": "bludgeoning", "properties": []}
    state = _social_state("diplomat_objection", {**action, "kind": "attack"})
    session = make_context().userdata
    session.combat_state = state
    player = state.get_participant("player_1")
    assert player is not None
    before = player.hp_current
    deps = _packet_deps(_damage_resolver(4))

    packets = await combat_hold.pump(
        session,
        state,
        packet_deps=deps,
        contest_rng=SequenceRng([10, 8] if won else [5, 10]),
    )

    reaction = next(row for row in packets if row.get("declaration_type") == "reaction")
    assert reaction["mechanical_effect"] == effect
    assert (reaction["reactor_total"], reaction["opposer_total"]) == totals
    assert before - player.hp_current == damage
    if won:
        hesitation = next(row for row in packets if row.get("hesitated"))
        assert hesitation == {"actor_id": "enemy_1", "resolved": False, "hesitated": True}
        deps["resolver"].resolve_attack.assert_not_called()


def test_combat_prompt_names_accusation_targets_and_social_reaction_results():
    assert "kind `accusation`" in COMBAT_PROMPT
    assert "target_id is the accused" in COMBAT_PROMPT
    for effect in ("command_countered", "accusation_dismissed", "action_hesitated"):
        assert effect in COMBAT_PROMPT
    assert "reactor_total" in COMBAT_PROMPT and "opposer_total" in COMBAT_PROMPT
    assert "never voice their raw numbers" in COMBAT_PROMPT
