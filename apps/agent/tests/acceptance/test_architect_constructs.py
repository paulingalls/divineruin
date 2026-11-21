from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_entomb import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_entomb import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_entomb import strike
from acceptance.test_architect_fight import attack, declare_attack, enter, pos, reopen
from acceptance.test_architect_terrain import set_favor
from acceptance.test_still_anchors import fresh_session
from sample_fixtures import published_payloads

import combat_spatial
import combat_structures
import db_mutations
from combat_participant import CombatParticipant
from db_mutations_resonance import read_player_resonance


def discover_summon(fight):
    for actor in fight.roster:
        for action in actor["executable_actions"]:
            if action["id"] == "Summon Constructs":
                assert action["available"] and action["declaration_type"] == "ability"
                return actor["id"], action["id"]
    pytest.fail("Summon Constructs is absent from the executable roster")


def summon_declaration(fight):
    owner, action = discover_summon(fight)
    return {
        "reshape": [],
        "actor_id": owner,
        "kind": "ability",
        "action": action,
        "targets": [],
        "argument_type": "",
    }


async def summon(fight, count, *, reload_pending=False):
    declaration = summon_declaration(fight)
    owner, action = declaration["actor_id"], declaration["action"]
    await fight.command("declare_phase", {"declarations": [declaration]})
    if reload_pending:
        pending = await fight.reload()
        assert not pending.architect_encounter["construct_ids"]
        assert pending.get_participant(owner).action_ledger[action.casefold()]["remaining"] == 1
        await fresh_session(fight, pending)
    with patch("architect_constructs.roll", return_value=SimpleNamespace(total=count)) as roll:
        packets = await fight.drain()
    roll.assert_called_once_with("2d4")
    return owner, declaration, packets


@pytest.mark.parametrize("count", [2, 5, 8])
async def test_summon_joins_the_next_round_and_spends_once(fight, count):
    owner, declaration, packets = await summon(fight, count)
    state = await fight.reload()
    ids = state.architect_encounter["construct_ids"]
    assert len(ids) == len(set(ids)) == count
    receipt = next(packet for packet in packets if packet["actor_id"] == owner)
    assert receipt["construct_ids"] == ids
    assert (receipt["summon_round"], receipt["construct_first_round"], receipt["construct_expiry_round"]) == (1, 2, 12)
    assert not state.held_actions and not state.pending_declarations
    assert not set(ids).intersection(packet["actor_id"] for packet in packets)
    start = state.initiative_order.index(owner) + 1
    assert state.initiative_order[start : start + count] == ids
    for actor_id in ids:
        actor = state.get_participant(actor_id)
        assert (actor.type, actor.hp_current, actor.hp_max, actor.ac) == ("enemy", 20, 20, 16)
        assert state.spatial["speeds"][actor_id] == 30
        positions = state.spatial["positions"]
        assert combat_spatial.distance(positions[actor_id], positions[owner]) <= 10
        assert positions[actor_id]["z"] == positions[owner]["z"]
        [slam] = actor.action_pool
        assert (slam["name"], slam["type"], slam["reach"], slam["attack_source"]) == ("Slam", "melee", 5, "catalog")
        assert (slam["to_hit"], slam["damage"], slam["damage_type"]) == (8, "1d8+5", "bludgeoning")
    roster = fight.last_result["participants"]
    spent = next(
        a
        for actor in roster
        if actor["id"] == owner
        for a in actor["executable_actions"]
        if a["id"] == declaration["action"]
    )
    assert (spent["available"], spent["reason"]) == (False, "spent")
    before = await fight.snapshot()
    events = published_payloads(fight.sd.room)
    assert "unavailable" in await fight.command("declare_phase", {"declarations": [declaration]}, error=True)
    assert await fight.snapshot() == before
    assert published_payloads(fight.sd.room) == events


async def test_no_walls_and_unresolved_declaration_survives_reconnect(fight):
    state = await fight.reload()
    for wall_id in state.architect_encounter["structure_ids"]:
        combat_structures.collapse_wall(state, state.get_participant(wall_id))
    owner = state.get_participant(state.architect_encounter["owner_id"])
    assert not state.spatial["structures"] and not owner.is_fallen
    combat_spatial.place(state, owner.id, pos(7, 8, 12))
    await fight.persist()
    await summon(fight, 5, reload_pending=True)
    state = await fight.reload()
    ids = state.architect_encounter["construct_ids"]
    assert len(ids) == 5
    assert not state.spatial["structures"]
    assert all(combat_spatial.distance(state.spatial["positions"][actor_id], pos(7, 8, 12)) <= 10 for actor_id in ids)


async def test_ally_fate_hold_delays_summon_without_spending_or_aging_it(fight):
    declaration = summon_declaration(fight)
    owner, player = declaration["actor_id"], fight.players[0]
    await set_favor(fight, "zhael", 40)
    await fight.command("declare_phase", {"declarations": [declaration, strike(player, owner, "Longsword")]})
    with (
        patch("architect_constructs.roll", return_value=SimpleNamespace(total=2)) as summons,
        patch("check_resolution.dice_roll", return_value=_d20(13)) as attacks,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        offered = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offered["roller_id"], offered["roll_kind"]) == (player, "attack")
        pending = await fight.reload()
        assert pending.ally_continuation is not None and pending.round_number == 1
        assert not pending.architect_encounter["construct_ids"]
        summons.assert_not_called()
        await fresh_session(fight, pending)
        await fight.drain()
    summons.assert_called_once_with("2d4")
    attacks.assert_called_once()
    state = await fight.reload()
    assert len(state.architect_encounter["construct_ids"]) == 2
    assert state.get_participant(owner).action_ledger["summon constructs"] == {"remaining": 0, "round": 1}
    assert state.round_number == 2


async def test_grouped_slam_turns_use_catalog_modifier_and_damage(fight):
    state = await fight.reload()
    owner = state.get_participant(state.architect_encounter["owner_id"])
    player = state.get_participant(fight.players[0])
    player.ac = 20
    other = CombatParticipant("other", "Other enemy", "enemy", owner.initiative, 10, 10, 10)
    other.attributes["dexterity"] = owner.attributes["dexterity"] - 1
    state.participants.append(other)
    state.initiative_order.insert(state.initiative_order.index(owner.id) + 1, other.id)
    state.spatial["positions"][other.id] = pos(30)
    state.spatial["speeds"][other.id] = 30
    await fight.persist()
    await summon(fight, 2)
    returned = {p["id"]: p["executable_actions"] for p in fight.last_result["participants"]}
    state = await fight.reload()
    ids = state.architect_encounter["construct_ids"]
    start = state.initiative_order.index(owner.id)
    assert state.initiative_order[start : start + 4] == [owner.id, *ids, other.id]
    combat_spatial.place(state, player.id, pos(0))
    await fight.persist()
    for include_owner, face in ((True, 12), (False, 11)):
        hit = include_owner
        declarations = [
            strike(actor_id, player.id, next(a["id"] for a in returned[actor_id] if a["declaration_type"] == "attack"))
            for actor_id in ids
        ]
        order = [*ids, other.id]
        declarations.append(defend(other.id))
        if include_owner:
            declarations.append(defend(owner.id))
            order.insert(0, owner.id)
        await fight.command("declare_phase", {"declarations": list(reversed(declarations))})
        with (
            patch("check_resolution.dice_roll", return_value=_d20(face)) as attacks,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)) as damage,
        ):
            packets = await fight.drain()
        assert [p["actor_id"] for p in packets] == order
        assert [p["hit"] for p in packets if p["actor_id"] in ids] == [hit, hit]
        assert attacks.call_count == 2 and damage.call_count == (2 if hit else 0)
        assert all(args.args[0] == "1d8+5" for args in damage.call_args_list)
        assert (await fight.reload()).get_participant(player.id).hp_current == 82


async def test_construct_stops_at_zero_and_surviving_slam_resumes_from_a_hold(fight):
    await summon(fight, 2)
    state = await fight.reload()
    target, survivor = state.architect_encounter["construct_ids"]
    player = fight.players[0]
    combat_spatial.place(state, player, pos(0))
    await fight.persist()

    result, _, _ = await attack(fight, player, target, "Longsword", face=19, damage=19)
    assert result["damage"] == 20
    state = await fight.reload()
    dropped = state.get_participant(target)
    assert dropped.hp_current == 0 and dropped.is_fallen
    assert not fight.last_result["death_saves_due"]
    wound, _, _ = await attack(fight, player, survivor, "Longsword", face=19, damage=3)
    assert wound["damage"] == 4
    state = await fight.reload()
    actor = state.get_participant(player)
    actor.reaction_ids = ["cleric_shield_of_faith"]
    actor.has_reaction_ability = True
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [strike(p, player, "Slam") for p in (target, survivor)]})
    await fight.command("resolve_phase", {})
    paused = await fight.command("resolve_phase", {})
    assert paused["next"]["waiting_on"]["stage"] == "pre_roll"
    held = await fight.reload()
    assert held.held_actions[0]["actor_id"] == survivor
    assert held.get_participant(survivor).hp_current == 16
    before = held.to_dict()
    await fresh_session(fight, held)
    assert (await fight.reload()).to_dict() == before
    with (
        patch("architect_constructs.roll") as summon_roll,
        patch("check_resolution.dice_roll", return_value=_d20(19)) as attacks,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(9)) as damage,
    ):
        packets = await fight.drain()
    summon_roll.assert_not_called()
    attacks.assert_called_once()
    damage.assert_called_once()
    assert [p["actor_id"] for p in packets if p.get("damage")] == [survivor]
    settled = await fight.reload()
    assert settled.get_participant(player).hp_current == actor.hp_current - 9
    assert settled.get_participant(target).is_fallen and settled.get_participant(survivor).hp_current == 16
    assert settled.round_number == held.round_number + 1


async def test_flee_reentry_keeps_summons_and_the_last_acting_round(fight):
    player = fight.players[0]
    await fight.command("declare_phase", {"declarations": [defend(player)]})
    await fight.drain()
    owner, declaration, packets = await summon(fight, 2)
    receipt = next(p for p in packets if p["actor_id"] == owner)
    assert (receipt["summon_round"], receipt["construct_first_round"], receipt["construct_expiry_round"]) == (2, 3, 13)
    state = await fight.reload()
    ids = state.architect_encounter["construct_ids"]
    combat_spatial.place(state, player, pos(0))
    await fight.persist()
    await attack(fight, player, ids[0], "Longsword", face=19, damage=19)
    await attack(fight, player, ids[1], "Longsword", face=19, damage=5)
    before = await fight.reload()
    assert before.round_number == 5
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    after = await enter(fight)
    assert after.architect_encounter is not None and after.spatial is not None
    assert after.round_number == before.round_number
    assert after.architect_encounter["construct_ids"] == ids
    restored_owner = after.get_participant(owner)
    assert restored_owner is not None
    assert restored_owner.action_ledger == before.get_participant(owner).action_ledger
    start = after.initiative_order.index(owner) + 1
    assert after.initiative_order[start : start + 2] == ids
    for actor_id in ids:
        saved = before.get_participant(actor_id)
        restored = after.get_participant(actor_id)
        assert restored is not None
        assert restored.initiative == restored_owner.initiative
        assert (restored.hp_current, restored.is_fallen) == (saved.hp_current, saved.is_fallen)
        for field in ("positions", "speeds"):
            assert after.spatial[field][actor_id] == before.spatial[field][actor_id]
    for expected in range(6, 13):
        await fight.command("declare_phase", {"declarations": [defend(player)]})
        await fight.drain()
        current = await fight.reload()
        assert current.round_number == expected and current.get_participant(ids[1]).hp_current == 14
    combat_spatial.place(current, player, current.spatial["positions"][ids[1]])
    await fight.persist()
    slam, _, _ = await attack(fight, ids[1], player, "Slam", face=19, damage=9)
    assert slam["hit"] and slam["damage"] == 9
    expired = await fight.reload()
    assert expired.round_number == 13 and not expired.get_participant(owner).is_fallen
    assert fight.last_result["architect"]["construct_expiry_round"] == 13
    for actor_id in ids:
        p = expired.get_participant(actor_id)
        assert p.hp_current == 0 and p.is_fallen and p.is_dead
    assert "unavailable" in await fight.command("declare_phase", {"declarations": [declaration]}, error=True)
    with patch("check_resolution.dice_roll") as roll:
        await declare_attack(fight, ids[1], player, "Slam")
        assert not any(packet.get("damage") for packet in await fight.drain())
    roll.assert_not_called()


async def test_lethal_hit_collapses_healthy_summons_in_first_saved_snapshot(fight, monkeypatch):
    owner, _, _ = await summon(fight, 2)
    player = fight.players[0]
    state = await fight.reload()
    record = state.architect_encounter
    state.get_participant(owner).hp_current = 1
    await fight.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player, '{"class":"mage"}')
    resonance = (await read_player_resonance(player))["current"]
    await fight.persist()
    saved = []
    original = db_mutations.save_combat_state

    async def capture(combat_id, data, **kwargs):
        await original(combat_id, data, **kwargs)
        if data["architect_encounter"]["phase"] == "destroyed":
            saved.append(deepcopy(data))

    monkeypatch.setattr(db_mutations, "save_combat_state", capture)
    await declare_attack(fight, player, owner, "Longsword")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await fight.drain()
    first = saved[0]
    assert not first["spatial"]["structures"]
    collapsed = set(record["construct_ids"] + record["structure_ids"])
    defeated = [p for p in first["participants"] if p["id"] in collapsed]
    assert {p["id"] for p in defeated} == collapsed
    assert all(p["hp_current"] == 0 and p["is_fallen"] and p["is_dead"] for p in defeated)
    assert all(not p["xp_value"] and not p["category"] and not p["loot_table_id"] for p in defeated)
    assert fight.last_result["outcome"] == "victory" and fight.last_result["xp_granted"] == 5000
    assert (await read_player_resonance(player))["current"] == resonance + 8
    assert await db_mutations.load_combat_state(state.combat_id) is None
