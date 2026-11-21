import json
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_entomb import favor, spell, strike
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos

import check_resolution_attack
import concentration_break
import db_mutations
import db_queries
import still_actions
import still_encounter
from combat_fate_rolls import PacketRolls, PhaseRolls
from combat_packet import _resolve_one_packet
from combat_participant import CombatParticipant
from combat_phase import ResolutionPacket
from conditions import apply_condition
from creature_combat import translate_creature
from declarations import Declaration, DeclarationType


async def catalog_actor(fight, state, creature_id):
    row = json.loads(await fight.pool.fetchval("SELECT data FROM creatures WHERE id=$1", creature_id))
    translated = translate_creature(row, encounter_id=state.encounter_id, enemy_id=creature_id, role="standard")
    actor = CombatParticipant(
        creature_id,
        translated["name"],
        "enemy",
        20,
        translated["hp"],
        translated["hp"],
        translated["ac"],
        creature_id=creature_id if creature_id == "hollow_still" else None,
        hollow=translated["hollow"],
        action_pool=translated["action_pool"],
        damage_affinities=translated["damage_affinities"],
    )
    state.participants.append(actor)
    state.initiative_order.append(actor.id)
    state.spatial["positions"][actor.id] = pos(4)
    state.spatial["speeds"][actor.id] = translated["speed"]
    return actor


def architect_result(packets, actor_id, owner, action):
    packet = next(packet for packet in packets if packet["actor_id"] == actor_id)
    if action == "floor":
        (floor,) = packet["reshape"]
        return next(result for result in floor["results"] if result["target_id"] == owner)
    if "targets" in packet:
        return next(result for result in packet["targets"] if result["target_id"] == owner)
    return packet


@pytest.mark.parametrize(
    "creature,action,kind,expected",
    [
        ("cult_leader", "Hold Person", "ability", {"condition_resisted": "paralyzed"}),
        ("hollow_veilrender", "Reality Crush", "area", {"damage": 4, "conditions_inflicted": []}),
        ("hollow_choir", "Cacophony", "area", {"damage": 4, "conditions_inflicted": ["deafened"]}),
        ("hollow_choir", "Stolen Melody", "ability", {}),
        ("hollow_still", "Final Stillness", "zone", {"stunned_rounds": 1}),
        (None, "floor", "reshape", {}),
    ],
)
async def test_phase_tool_surfaces_save_override(fight, creature, action, kind, expected):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    caster = await catalog_actor(fight, state, creature) if creature else state.get_participant(owner)
    state.spatial["positions"][fight.players[0]] = pos(30)
    if kind == "zone":
        still_encounter.initialize(state)
        record = state.still_encounter
        for key in record["anchor_ids"][:4]:
            anchor = state.get_participant(key)
            anchor.hp_current = 0
            anchor.is_fallen = True
            record["revealed_ids"].append(key)
        caster.hp_current = sum(state.get_participant(key).hp_current for key in record["anchor_ids"])
        caster.still_dormant = False
        caster.action_ledger[action.casefold()]["remaining"] = 1
        declaration = {**spell(caster.id, action, owner), "targets": []}
    elif kind == "reshape":
        caster.hp_current = (caster.hp_max - 1) // 2
        declaration = {
            "actor_id": caster.id,
            "kind": "defend",
            "reshape": [{"kind": "open_floor", "min": pos(-2, -2), "max": pos(2, 2)}],
        }
    elif kind == "area":
        state.spatial["positions"][fight.players[0]] = pos(10)
        declaration = strike(caster.id, fight.players[0], action)
    else:
        declaration = spell(caster.id, action, owner)
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [declaration]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(8)),
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        result = architect_result(await fight.drain(), caster.id, owner, action)
    assert result["save_success"], result
    assert result["success_override"] == "Legendary Resistance"
    for field, value in expected.items():
        assert result[field] == value
    state = await fight.reload()
    assert state.get_participant(owner).action_ledger["legendary resistance"]["remaining"] == 2
    assert owner not in state.architect_encounter["pits"]


@pytest.mark.parametrize(
    "creature,action,damage,held",
    [
        ("hollow_choir", "Dissonant Chord", 7, False),
        ("hollow_still", "Serenity's Touch", 7, False),
        ("hollow_knight", "Corrupted Blade", None, False),
        ("hollow_knight", "Corrupted Blade", None, True),
    ],
)
async def test_strike_packet_keeps_hit_damage_and_negates_failed_rider(fight, creature, action, damage, held):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    actor = await catalog_actor(fight, state, creature)
    if creature == "hollow_still":
        still_encounter.initialize(state)
        actor.still_dormant = False
    target = state.get_participant(owner)
    target.attributes["constitution"] = 10
    target.saving_throw_proficiencies = []
    packet = ResolutionPacket(actor.id, Declaration(DeclarationType.ATTACK, action, owner), actor.initiative)
    resolve_packet = partial(
        _resolve_one_packet,
        fight.sd,
        state,
        packet,
        mutations=db_mutations,
        queries=db_queries,
        resolver=check_resolution_attack,
        concentration_break_mod=concentration_break,
        publish_roll=False,
    )
    if held:
        await favor(fight)
    with (
        patch(
            "check_resolution.dice_roll",
            side_effect=[_d20(19 if creature == "hollow_choir" else 20), _d20(1)]
            if creature != "hollow_still"
            else [_d20(1)],
        ),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)),
        patch("dice.roll", return_value=_damage_die(7)),
    ):
        if creature == "hollow_still":
            result = await still_actions.resolve_touch(
                fight.sd,
                state,
                actor,
                next(a for a in actor.action_pool if a["name"] == action),
                packet.declaration,
                head=None,
                progress=None,
                conn=None,
                mutations=db_mutations,
                queries=db_queries,
                concentration=concentration_break,
                sink=None,
                advantage=False,
            )
        elif held:
            phase = PhaseRolls()
            steps = {}
            async with fight.sd.fate_lock:
                pending = await resolve_packet(progress=PacketRolls(phase, steps, db_queries, None))
            assert not pending and phase.pending is not None and phase.pending.roller_id == owner
            remaining_hp = target.hp_current
            assert remaining_hp < target.hp_max and not target.conditions
            assert target.action_ledger["legendary resistance"]["remaining"] == 3
            result = await resolve_packet(
                progress=PacketRolls(PhaseRolls(), json.loads(json.dumps(steps)), db_queries, None)
            )
            assert target.hp_current == remaining_hp
        else:
            result = await resolve_packet()
    save = result["critical_save"] if creature == "hollow_knight" else result
    assert save.get("success", save.get("save_success")), result
    assert save["success_override"] == "Legendary Resistance"
    if damage is not None:
        assert result["damage"] == damage
    assert result["damage"] > 0 and result["damage"] == target.hp_max - target.hp_current
    assert target.action_ledger["legendary resistance"]["remaining"] == 2
    assert not target.conditions


@pytest.mark.parametrize(
    "action,rolled,immune,spent,damage",
    [
        ("Stolen Melody", 0, True, False, 0),
        ("Reality Crush", 8, False, True, 4),
        ("Reality Crush", 8, True, False, 8),
        ("Reality Crush", 25, True, True, 12),
        ("Reality Crush", 25, "poison", False, 0),
    ],
)
async def test_condition_and_damage_eligibility_are_independent(fight, action, rolled, immune, spent, damage):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    target = state.get_participant(owner)
    target.hp_current = 40
    state.spatial["positions"][fight.players[0]] = pos(10)
    if action == "Stolen Melody":
        actor = await catalog_actor(fight, state, "hollow_choir")
        target.conditions = apply_condition(target.conditions, "temporary_hollowed")
        declaration = spell(actor.id, action, owner)
    else:
        actor = await catalog_actor(fight, state, "hollow_veilrender")
        if immune:
            target.prone_immunity = "Stable footing"
        if immune == "poison":
            next(a for a in actor.action_pool if a["name"] == action)["damage_type"] = "poison"
        declaration = strike(actor.id, fight.players[0], action)
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [declaration]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(rolled)),
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        result = architect_result(await fight.drain(), actor.id, owner, action)
    assert result["save_success"] is spent
    assert result.get("success_override") == ("Legendary Resistance" if spent else None)
    target = (await fight.reload()).get_participant(owner)
    assert target.hp_current == 40 - damage
    assert not {"charmed", "prone"} & {condition["type"] for condition in target.conditions}
    assert target.action_ledger["legendary resistance"]["remaining"] == 3 - spent
