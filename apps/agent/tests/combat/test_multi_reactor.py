"""Every spend bound to one reaction window reaches resolution."""

import json
import random
from unittest.mock import patch

import pytest
from combat._helpers import _ac_sensitive_resolver, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import _drain, _enemy_blow, _guarded_ally_state, _pause_at

import combat_hold
import combat_reaction_contest
import combat_reaction_effect
import reaction_spend
import reaction_windows
from dice import roll as roll_dice
from session_data import CombatParticipant, CombatState


def _with_third_player(*, target_id="player_3"):
    state = _guarded_ally_state(target_id=target_id)
    state.participants.insert(
        2,
        CombatParticipant(
            id="player_3",
            name="Sable",
            type="player",
            initiative=16,
            hp_current=20,
            hp_max=20,
            ac=14,
            has_reaction_ability=True,
        ),
    )
    state.initiative_order.insert(2, "player_3")
    return state


def _spend_all(state, ordered):
    state.reactions_available.clear()
    for actor_id, ability_id in ordered:
        combat_hold.record_spend(
            state,
            actor_id,
            reaction_spend.spend(ability_id, state.open_window, held_seq=state.held_actions[0]["seq"]),
        )


def _reaction_packets(packets):
    return [packet for packet in packets if packet.get("declaration_type") == "reaction"]


@pytest.mark.asyncio
async def test_two_shields_apply_one_maximum_bonus_and_emit_two_packets():
    state = _with_third_player()
    ctx = _ctx_at_resolution(state=state)
    deps = {**_resolve_deps(), "resolver": _ac_sensitive_resolver(attack_total=15, damage=4)}
    packets = []
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    state = ctx.userdata.combat_state
    _spend_all(state, [("player_1", "cleric_shield_of_faith"), ("player_2", "oracle_shield_of_faith")])
    await _drain(ctx, deps, packets)

    blow = _enemy_blow(packets)
    reactions = _reaction_packets(packets)
    assert (blow["hit"], blow["target_ac"]) == (False, 16)
    assert {packet["actor_id"] for packet in reactions} == {"player_1", "player_2"}
    assert sorted((packet["mechanical_effect"] for packet in reactions), key=str) == [None, "target_ac_bonus"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_unwired_ally_spend_cannot_hide_targets_uncanny_dodge(reverse):
    state = _guarded_ally_state(target_id="player_1")
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps(damage=6)
    packets = []
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.POST_ROLL, packets=packets)
    state = ctx.userdata.combat_state
    spends = [("player_2", "guardian_intercept"), ("player_1", "rogue_uncanny_dodge")]
    _spend_all(state, list(reversed(spends)) if reverse else spends)
    await _drain(ctx, deps, packets)

    effects = {packet["actor_id"]: packet["mechanical_effect"] for packet in _reaction_packets(packets)}
    assert ctx.userdata.combat_state.get_participant("player_1").hp_current == 22
    assert _enemy_blow(packets)["damage"] == 3
    assert effects == {"player_1": "damage_halved", "player_2": None}


def _seeded_dice(seed):
    seeded_rng = random.Random(seed)

    def roll(notation, rng=None):
        return roll_dice(notation, rng=rng or seeded_rng)

    return roll


def _hollow_shriek_state():
    state = _guarded_ally_state()
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.action_pool = [
        {
            "name": "Hollow Shriek",
            "damage": "0",
            "damage_type": "psychic",
            "properties": ["control"],
            "applies_condition": "frightened",
            "save": "wisdom",
            "dc": 12,
        }
    ]
    state.pending_declarations[enemy.id]["action"] = "Hollow Shriek"
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_countercharm_and_shield_apply_save_advantage_in_either_order(reverse):
    state = _hollow_shriek_state()
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps()
    packets = []
    with patch("check_resolution.dice_roll", side_effect=_seeded_dice(1)):
        await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
        state = ctx.userdata.combat_state
        spends = [("player_1", "bard_countercharm"), ("player_2", "cleric_shield_of_faith")]
        _spend_all(state, list(reversed(spends)) if reverse else spends)
        await _drain(ctx, deps, packets)

    summary = next(packet for packet in packets if packet.get("condition_resisted") == "frightened")
    effects = {packet["ability_id"]: packet["mechanical_effect"] for packet in _reaction_packets(packets)}
    assert summary["save_advantage"] is True
    assert effects == {"bard_countercharm": "save_advantage", "cleric_shield_of_faith": None}


@pytest.mark.asyncio
async def test_two_countercharms_apply_advantage_once():
    state = _with_third_player(target_id="player_2")
    shrieker = _hollow_shriek_state().get_participant("goblin_scout_1")
    enemy = state.get_participant("goblin_scout_1")
    assert shrieker is not None and enemy is not None
    enemy.action_pool = shrieker.action_pool
    state.pending_declarations["goblin_scout_1"]["action"] = "Hollow Shriek"
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps()
    packets = []
    with patch("check_resolution.dice_roll", side_effect=_seeded_dice(1)):
        await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
        state = ctx.userdata.combat_state
        _spend_all(state, [("player_1", "bard_countercharm"), ("player_3", "diplomat_countercharm")])
        await _drain(ctx, deps, packets)

    summary = next(packet for packet in packets if packet.get("condition_resisted") == "frightened")
    assert summary["save_advantage"] is True
    assert sorted((packet["mechanical_effect"] for packet in _reaction_packets(packets)), key=str) == [
        None,
        "save_advantage",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_winning_objection_leaves_other_spends_null(reverse):
    state = _guarded_ally_state()
    reactor = state.get_participant("player_1")
    enemy = state.get_participant("goblin_scout_1")
    assert reactor is not None and enemy is not None
    reactor.attributes = {"charisma": 16}
    enemy.attributes = {"wisdom": 16}
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps(damage=4)
    packets = []
    await _pause_at(ctx, deps, actor_id="goblin_scout_1", stage=reaction_windows.PRE_ROLL, packets=packets)
    state = ctx.userdata.combat_state
    spends = [("player_1", "diplomat_objection"), ("player_2", "cleric_shield_of_faith")]
    _spend_all(state, list(reversed(spends)) if reverse else spends)
    before = state.get_participant("player_2").hp_current
    deps.pop("db_mod")
    deps.pop("character_spells_mod")
    packets.extend(await combat_hold.pump(ctx.userdata, state, packet_deps=deps, contest_rng=SequenceRng([10, 8])))

    effects = {packet["ability_id"]: packet["mechanical_effect"] for packet in _reaction_packets(packets)}
    assert effects == {"diplomat_objection": "action_hesitated", "cleric_shield_of_faith": None}
    hesitation = next(packet for packet in packets if packet.get("hesitated"))
    assert hesitation["reason"] == "Objection raised by player_1"
    assert state.get_participant("player_2").hp_current == before
    deps["resolver"].resolve_attack.assert_not_called()


class SequenceRng:
    def __init__(self, values):
        self.values = iter(values)

    def randint(self, _low, _high):
        return next(self.values)


class RefusingRng:
    def randint(self, _low, _high):
        raise AssertionError("stored contests must not reroll")


def _social_state(spends):
    state = _with_third_player()
    action = {"name": "Rally", "kind": "command", "properties": []}
    enemy = state.get_participant("goblin_scout_1")
    assert enemy is not None
    enemy.action_pool = [action]
    enemy.attributes = {"charisma": 12, "wisdom": 16}
    for actor_id in ("player_1", "player_2", "player_3"):
        reactor = state.get_participant(actor_id)
        assert reactor is not None
        reactor.attributes = {"charisma": 16}
    state.held_actions = [
        {
            "seq": 0,
            "actor_id": enemy.id,
            "initiative": enemy.initiative,
            "declaration": {"type": "attack", "action": "Rally", "target_id": "player_3"},
            "roll": None,
            "roll_published": False,
            "opened": [reaction_windows.PRE_ROLL],
        }
    ]
    state.open_window = reaction_windows.open_window_for(
        round_number=1,
        seq=0,
        stage=reaction_windows.PRE_ROLL,
        actor_id=enemy.id,
        target_id="player_3",
        action_kind="command",
        triggers=reaction_windows.pre_roll_triggers(action),
    )
    _spend_all(state, spends)
    return state


def _close_social(state, rng):
    return combat_reaction_effect.close(
        state, state.held_actions[0], state.open_window, attack_action=None, contest_rng=rng
    )


def test_social_contests_persist_per_reactor_across_round_trip():
    state = _social_state([("player_1", "marshal_countermand"), ("player_2", "diplomat_objection")])
    packets = _close_social(state, SequenceRng([10, 8, 5, 10]))

    assert [packet["mechanical_effect"] for packet in packets] == ["command_countered", None]
    contests = state.held_actions[0]["reaction_contests"]
    assert set(contests) == {"player_1", "player_2"}
    assert contests["player_1"]["reactor_total"] != contests["player_2"]["reactor_total"]
    reloaded = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert _close_social(reloaded, RefusingRng()) == packets


def test_losing_contest_cannot_hide_later_wins():
    losing = {"ability_id": "diplomat_objection", "reactor_total": 8, "opposer_total": 13, "success": False}
    cancellation = {"ability_id": "marshal_countermand", "reactor_total": 13, "opposer_total": 9, "success": True}
    hesitation = {"ability_id": "diplomat_objection", "reactor_total": 13, "opposer_total": 11, "success": True}
    head = {"reaction_contests": {"player_1": losing, "player_2": cancellation}}
    assert combat_reaction_contest.mark_cancelled(head) is True
    head["reaction_contests"]["player_2"] = hesitation
    assert combat_reaction_contest.hesitated(head) is True


def test_legacy_singular_contest_upgrades_to_its_only_matching_reactor():
    state = _social_state([("player_1", "marshal_countermand")])
    result = {
        "ability_id": "marshal_countermand",
        "reactor_total": 13,
        "opposer_total": 9,
        "success": True,
    }
    state.held_actions[0]["reaction_contest"] = result
    reloaded = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))

    assert reloaded.held_actions[0]["reaction_contests"] == {"player_1": result}
    assert "reaction_contest" not in reloaded.held_actions[0]
    assert _close_social(reloaded, RefusingRng())[0]["reactor_total"] == 13


@pytest.mark.parametrize("case", ["no_match", "two_matches", "both_shapes"])
def test_legacy_contest_upgrade_refuses_ambiguous_attribution(case):
    spends = [("player_1", "diplomat_objection")]
    if case == "two_matches":
        spends = [("player_1", "marshal_countermand"), ("player_2", "marshal_countermand")]
    state = _social_state(spends)
    head = state.held_actions[0]
    head["reaction_contest"] = {
        "ability_id": "marshal_countermand",
        "reactor_total": 13,
        "opposer_total": 9,
        "success": True,
    }
    if case == "both_shapes":
        head["reaction_contests"] = {"player_1": head["reaction_contest"]}
    with pytest.raises(ValueError, match="reaction contest"):
        CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
