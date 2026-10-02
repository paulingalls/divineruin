import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from combat._catalog_actions import BITE, DIRTY, RALLY
from combat._catalog_fixtures import deps, hold, setup, wrap
from sample_fixtures import make_context

import combat_hold
from combat_packet import _resolve_one_packet
from combat_phase import advance_combat_phase
from combat_support import _participant_summary
from declarations import Declaration, DeclarationType
from encounter_roles import derive_role_stats


def ability(packet):
    packet.declaration = Declaration(type=DeclarationType.ABILITY, action=packet.declaration.action)


async def test_captain_rally_heals_only_eligible_bandits_and_caps_each():
    state, actor, packet = setup(RALLY)
    actor.creature_id = "bandit_captain"
    actor.hp_current = 3
    allied = copy.deepcopy(actor)
    allied.id = "another"
    allied.creature_id = "bandit"
    allied.hp_current = 6
    foreign = copy.deepcopy(allied)
    foreign.id = "other_species"
    foreign.creature_id = "goblin"
    fallen = copy.deepcopy(allied)
    fallen.id = "fallen"
    fallen.is_fallen = True
    dead = copy.deepcopy(allied)
    dead.id = "dead"
    dead.is_dead = True
    zero = copy.deepcopy(allied)
    zero.id = "zero"
    zero.hp_current = 0
    state.participants.extend([allied, foreign, fallen, dead, zero])
    state.participants[0].hp_current = 10
    ability(packet)
    d = deps()
    with patch("dice.roll", return_value=SimpleNamespace(total=5)) as healing_roll:
        summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    healing_roll.assert_called_once_with("1d8")
    assert summary["resolved"]
    assert [p.hp_current for p in state.participants] == [10, 7, 7, 6, 6, 6, 0]
    assert summary["healed"] == {actor.id: 4, allied.id: 1}
    d["resolver"].resolve_attack.assert_not_called()
    assert "Rally" not in _participant_summary(actor)["actions"]


def test_captain_actives_are_produced_and_declarable():
    state, actor, _packet = setup(RALLY)
    actor.action_pool.append(DIRTY)
    roster = _participant_summary(actor)
    assert roster["mark_actions"] == []
    assert roster["executable_actions"] == [
        {"name": "Rally", "kind": "healing", "declaration_type": "ability"},
        {"name": "Dirty Fighting", "kind": "prepare_attack", "declaration_type": "ability"},
    ]
    advance_combat_phase(state, declarations={actor.id: {"type": "ability", "action": "Rally"}})


async def prepared(seed=0, action=DIRTY):
    state, actor, packet = setup(action)
    actor.action_pool.append({"name": "Scimitar", "damage": "1d1", "damage_type": "slashing"})
    ability(packet)
    d = deps(seed)
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert summary["resolved"]
    packet.declaration = Declaration(type=DeclarationType.ATTACK, action="Scimitar", target_id="player_1")
    return state, actor, packet, d


async def test_dirty_fighting_next_attack_advantage_and_one_round_blind():
    import json
    from pathlib import Path

    catalog = json.loads((Path(__file__).parents[4] / "content/creatures.json").read_text())
    captain = next(row for row in catalog if row["id"] == "bandit_captain")
    dirty = next(action for action in captain["actives"] if action["name"] == "Dirty Fighting")
    state, _actor, packet, d = await prepared(action=dirty)
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert summary["roll"] == 14
    assert summary["condition_inflicted"] == "blinded"
    assert state.participants[0].conditions[0]["duration"] == 1
    second = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert second["roll"] == 13
    assert "condition_inflicted" not in second
    from combat_state import CombatState

    state = CombatState.from_dict(state.to_dict())
    state = await wrap(state)
    from conditions import get_condition_effects

    assert "attack" in get_condition_effects(state.participants[0].conditions).disadvantage_scopes
    player_packet = SimpleNamespace(
        actor_id=state.participants[0].id,
        declaration=Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id=state.participants[1].id),
    )
    state.participants[1].hp_current = state.participants[1].hp_max = 100
    player_deps = deps(5)
    player_hit = await _resolve_one_packet(make_context().userdata, state, player_packet, **player_deps)
    assert player_hit["roll"] == 9
    unblinded = copy.deepcopy(state)
    unblinded.participants[0].conditions = []
    normal_hit = await _resolve_one_packet(make_context().userdata, unblinded, player_packet, **deps(5))
    assert normal_hit["roll"] == 20
    state = await wrap(state)
    assert not state.participants[0].conditions


async def test_dirty_fighting_miss_consumes_without_blind():
    state, actor, packet, d = await prepared(seed=2)
    state.participants[0].ac = 50
    first = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert not first["hit"]
    assert not state.participants[0].conditions
    assert actor.pending_preparation is None
    second = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert second["roll"] == 2


@pytest.mark.parametrize("hp, damage, healed", [(3, 20, 3), (25, 20, 4), (25, 0, 0)])
async def test_absorb_heals_only_actual_hp_removed_and_caps(hp, damage, healed):
    state, actor, packet = setup({**BITE, "damage": f"1d1+{max(0, damage - 1)}"})
    state.participants[0].hp_current = hp
    actor.hp_current = 3
    if damage == 0:
        actor.damage_mult = 0
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert actor.hp_current == 3 + healed
    assert summary.get("self_healed", 0) == healed


async def test_absorb_miss_does_not_heal():
    state, actor, packet = setup(BITE)
    actor.hp_current = 3
    state.participants[0].ac = 100
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **deps(2))
    assert not summary["hit"]
    assert actor.hp_current == 3


def test_captain_minion_strips_both_actives():
    result = derive_role_stats({"hp": 10, "action_pool": [RALLY, DIRTY]}, "minion")
    assert result["action_pool"] == []


async def test_dirty_fighting_nonattack_does_not_consume():
    state, actor, packet, d = await prepared()
    packet.declaration = Declaration(type=DeclarationType.DEFEND)
    await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert actor.pending_preparation is not None
    d["resolver"].resolve_attack.assert_not_called()


async def test_dirty_fighting_held_reload_applies_once_without_save():
    import json

    from session_data import CombatState

    state, actor, _packet, d = await prepared()
    actor.action_pool = [actor.action_pool[1], actor.action_pool[0]]
    hold(state, actor)
    with patch("check_resolution_save.roll_participant_save", side_effect=AssertionError("no authored save")):
        await combat_hold.pump(make_context().userdata, state, packet_deps=d)
        await combat_hold.pump(make_context().userdata, state, packet_deps=d)
        assert actor.pending_preparation is None
        state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
        result = await combat_hold.pump(make_context().userdata, state, packet_deps=d)
    assert result[0]["condition_inflicted"] == "blinded"
    assert state.participants[0].conditions[0]["duration"] == 1
    assert len(state.participants[0].conditions) == 1
    assert d["resolver"].resolve_attack.call_count == 1


async def test_prepared_hit_respects_condition_immunity():
    state, _actor, packet, d = await prepared()
    state.participants[0].condition_immunities = {"blinded": "Eyeless"}
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert summary["condition_immune"] == "blinded"
    assert not state.participants[0].conditions


@pytest.mark.parametrize("live_hp", [7, 25])
async def test_absorb_heals_post_mitigation_live_loss_once_on_reload(live_hp):
    import json

    import reaction_spend
    from session_data import CombatState

    state, actor, _packet = setup(BITE)
    actor.hp_current = 1
    actor.hp_max = 30
    hold(state, actor)
    d = deps()
    session = make_context().userdata
    await combat_hold.pump(session, state, packet_deps=d)
    await combat_hold.pump(session, state, packet_deps=d)
    state.participants[0].hp_current = live_hp
    assert state.open_window is not None
    state.reactions_available["player_1"] = reaction_spend.spend(
        "rogue_uncanny_dodge", state.open_window, held_seq=state.held_actions[0]["seq"]
    )
    state = CombatState.from_dict(json.loads(json.dumps(state.to_dict())))
    result = await combat_hold.pump(session, state, packet_deps=d)
    assert result[-1]["damage"] == 10
    assert result[-1]["self_healed"] == min(live_hp, 10)
    assert state.participants[1].hp_current == 1 + min(live_hp, 10)
    assert d["resolver"].resolve_attack.call_count == 1


async def test_absorb_hp_loss_precedes_hollowed_transform():
    state, actor, packet = setup(BITE)
    actor.hp_current = 1
    actor.hp_max = 30
    target = state.participants[0]
    target.hp_current = 3
    target.conditions = [{"type": "hollowed", "stage": 2}]
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert target.type == "temporary_hollowed"
    assert target.hp_current == 12
    assert summary["self_healed"] == 3
    assert actor.hp_current == 4


async def test_unsupported_ability_does_not_spend_or_consume_preparation():
    state, actor, packet, d = await prepared()
    action = actor.action_pool[1]
    action["recharge"] = {"kind": "encounter", "uses": 1}
    packet.declaration = Declaration(type=DeclarationType.ABILITY, action="Scimitar", target_id="player_1")
    before = copy.deepcopy(actor.pending_preparation)
    summary = await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert not summary["resolved"]
    assert actor.pending_preparation == before
    assert actor.action_ledger["scimitar"]["remaining"] == 1
    d["resolver"].resolve_attack.assert_not_called()


async def test_dirty_fighting_save_does_not_consume_preparation():
    state, actor, packet, d = await prepared()
    actor.action_pool.append(
        {
            "name": "Wave",
            "damage": "1d1",
            "damage_type": "necrotic",
            "half_on_success": True,
            "save": "constitution",
            "dc": 12,
        }
    )
    packet.declaration = Declaration(type=DeclarationType.ATTACK, action="Wave", target_id="player_1")
    await _resolve_one_packet(make_context().userdata, state, packet, **d)
    assert actor.pending_preparation is not None
    assert not state.participants[0].conditions
    d["resolver"].resolve_attack.assert_not_called()


async def test_condition_action_honors_authored_duration():
    state, _actor, packet = setup(
        {
            "name": "Dazzle",
            "damage": "0",
            "damage_type": "none",
            "applies_condition": "blinded",
            "duration": 1,
            "save": "constitution",
            "dc": 100,
        }
    )
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):
        summary = await _resolve_one_packet(make_context().userdata, state, packet, **deps())
    assert summary["condition_inflicted"] == "blinded"
    assert state.participants[0].conditions[0]["duration"] == 1
    state = await wrap(state)
    assert state.participants[0].conditions[0]["duration"] == 1
    state = await wrap(state)
    assert not state.participants[0].conditions


@pytest.mark.parametrize("action", [RALLY, DIRTY])
@pytest.mark.parametrize("objection", [False, True])
async def test_captain_actives_offer_only_catch_all_before_execution(action, objection):
    import reaction_gate
    import reaction_spend

    state, actor, _packet = setup(action)
    actor.creature_id = "bandit_captain"
    actor.hp_current = 1
    hold(state, actor)
    state.participants[0].reaction_ids = ["diplomat_objection", "skirmisher_sidestep", "marshal_countermand"]
    state.pending_declarations[actor.id] = {"type": "ability", "action": action["name"]}
    state.held_actions[0]["declaration"] = state.pending_declarations[actor.id]
    d = deps()
    session = make_context().userdata
    assert await combat_hold.pump(session, state, packet_deps=d) == []
    assert state.open_window is not None
    assert state.open_window["stage"] == "pre_roll"
    assert state.open_window["target_id"] is None
    assert state.open_window["triggers"] == ["on_enemy_action"]
    assert [row["id"] for row in reaction_gate.offered_reactions(state)] == ["diplomat_objection"]
    assert actor.hp_current == 1
    assert actor.pending_preparation is None
    assert action["name"] in _participant_summary(actor)["actions"]
    if objection:
        from unittest.mock import MagicMock

        state.participants[0].attributes["charisma"] = 18
        actor.attributes["wisdom"] = 10
        state.reactions_available["player_1"] = reaction_spend.spend(
            "diplomat_objection", state.open_window, held_seq=state.held_actions[0]["seq"]
        )
        result = await combat_hold.pump(
            session, state, packet_deps=d, contest_rng=SimpleNamespace(randint=MagicMock(side_effect=[20, 1]))
        )
        assert result[-1]["hesitated"]
        assert actor.hp_current == 1
        assert actor.pending_preparation is None
        assert action["name"] in _participant_summary(actor)["actions"]
    else:
        result = await combat_hold.pump(session, state, packet_deps=d)
        assert result[0]["resolved"]
        assert action["name"] not in _participant_summary(actor)["actions"]
    assert not state.held_actions
    assert state.open_window is None
    d["resolver"].resolve_attack.assert_not_called()
