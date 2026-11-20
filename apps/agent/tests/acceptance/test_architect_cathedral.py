from copy import deepcopy
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_entomb import favor, spell, strike
from acceptance.test_architect_entomb import fight as fight
from acceptance.test_architect_fight import declare_attack, enter, pos, reload_held, reopen
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_terrain import move, play

import check_resolution_save
import combat_spatial
import combat_structures
import db_mutations
from combat_participant import CombatParticipant
from conditions import apply_condition
from db_mutations_concentration import update_player_concentration


def discover(fight):
    return next(
        (
            (actor["id"], action["id"])
            for actor in fight.roster
            for action in actor["executable_actions"]
            if action["id"] == "Cathedral" and action["available"]
        ),
        None,
    )


async def test_cathedral_crushes_through_walls_and_spends_once(fight):
    cathedral = discover(fight)
    assert cathedral is not None
    owner, action = cathedral
    victim = fight.players[0]
    state = await fight.reload()
    center = pos(4, 6, 8)
    combat_spatial.place(state, owner, center)
    combat_spatial.place(state, victim, pos(34, 6, 8))
    combat_structures.add_wall(state, "partition", "Partition", pos(14, 0, 8), pos(14, 14, 8))
    before_cast = await fight.persist()
    wall_hp = {p.id: p.hp_current for p in before_cast.participants if p.is_structure}
    await declare_attack(fight, owner, victim, action)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(2)) as saves,
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(6)) as damage,
    ):
        cast = next(packet for packet in await fight.drain() if packet["actor_id"] == owner)
    saves.assert_called_once()
    damage.assert_called_once_with("1d8")
    assert [target["target_id"] for target in cast["targets"]] == [victim]
    result = cast["targets"][0]
    assert (result["save_type"], result["save_dc"], result["save_success"]) == ("dexterity", 20, False)
    state = await fight.reload()
    assert state.get_participant(victim).hp_current == 94
    assert {p.id: p.hp_current for p in state.participants if p.is_structure} == wall_hp
    caster = state.get_participant(owner)
    assert caster.hp_current == caster.hp_max
    assert caster.action_ledger["cathedral"]["remaining"] == 0
    (zone,) = (zone for zone in state.spatial["zones"].values() if zone.get("kind") == "cathedral")
    assert zone["radius_ft"] == 60
    assert state.spatial["locations"][zone["center_id"]] == center
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    restored = await enter(fight)
    restored_owner = restored.get_participant(owner)
    assert restored.spatial is not None and restored_owner is not None
    assert restored.spatial["zones"] == state.spatial["zones"]
    assert restored.spatial["locations"][zone["center_id"]] == center
    assert restored_owner.action_ledger["cathedral"]["remaining"] == 0
    before = await fight.snapshot()
    fight.sd.room.local_participant.publish_data.reset_mock()
    refused = await fight.command(
        "declare_phase",
        {"declarations": [strike(owner, victim, action)]},
        error=True,
    )
    assert "unavailable" in refused
    assert await fight.snapshot() == before
    fight.sd.room.local_participant.publish_data.assert_not_called()


async def cast_cathedral(fight):
    discovered = discover(fight)
    assert discovered is not None
    owner, action = discovered
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await play(fight, owner, strike(owner, fight.players[0], action))
    return owner


async def test_cathedral_defense_ends_on_first_exit(fight):
    owner = await cast_cathedral(fight)
    player = fight.players[0]
    state = await fight.reload()
    state.get_participant(player).attributes["strength"] = 10
    state.spatial["speeds"][owner] = 30
    await fight.persist()

    async def check_ac(expected):
        with (
            patch("check_resolution.dice_roll", return_value=_d20(17)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        ):
            summary = await play(fight, player, attack(player, owner))
        assert (summary["attack_total"], summary["target_ac"], summary["hit"]) == (20, expected, expected == 19)
        assert (await fight.reload()).get_participant(owner).ac == 19

    await check_ac(21)
    zone_id = next(key for key, zone in state.spatial["zones"].items() if zone.get("kind") == "cathedral")
    center_id = state.spatial["zones"][zone_id]["center_id"]
    for x in (30, 60):
        assert (await play(fight, owner, move(owner, pos(x))))["moved_ft"] == 30
    edge = await fight.reload()
    assert edge.spatial["locations"][center_id] == pos(0)
    assert edge.spatial["zones"][zone_id]["radius_ft"] == 60
    edge.spatial["positions"][player] = pos(60)
    await fight.persist()
    await check_ac(21)
    assert (await play(fight, owner, move(owner, pos(60, 0, 4), movement_mode="flying")))["moved_ft"] == 4
    outside = await fight.reload()
    assert zone_id not in outside.spatial["zones"]
    assert center_id not in outside.spatial["locations"]
    await check_ac(19)
    await play(fight, owner, move(owner, pos(60)))
    inside = await fight.reload()
    assert zone_id not in inside.spatial["zones"]
    assert inside.get_participant(owner).action_ledger["cathedral"]["remaining"] == 0
    await check_ac(19)
    state = await fight.reload()
    architect = state.get_participant(owner)
    architect.attributes["wisdom"] = 10
    architect.conditions = apply_condition([], "frightened", duration=3)
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [defend(player)]})
    with patch("check_resolution.dice_roll", return_value=_d20(9)) as saves:
        await fight.drain()
    saves.assert_called_once()
    assert (await fight.reload()).get_participant(owner).conditions[0]["type"] == "frightened"


@pytest.mark.parametrize("route", ["floor", "wrap", "spell", "ability"])
async def test_cathedral_bolsters_the_architects_saves(fight, route):
    owner = await cast_cathedral(fight)
    player = fight.players[0]
    state = await fight.reload()
    architect = state.get_participant(owner)
    for attribute in ("dexterity", "wisdom", "strength"):
        architect.attributes[attribute] = 10
    architect.saving_throw_proficiencies = []
    caster = state.get_participant(player)
    caster.attributes.update(wisdom=10, strength=10, dexterity=10)
    caster.saving_throw_proficiencies = []
    if route == "floor":
        floor = {"kind": "open_floor", "min": pos(-1, -2), "max": pos(6, 2)}
        actions = [{**defend(owner), "reshape": [floor]}]
        face = 14
    elif route == "wrap":
        architect.conditions = apply_condition([], "frightened", duration=3)
        actions = [defend(player)]
        face = 9
    elif route == "spell":
        await fight.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            player,
            '{"class":"cleric","attributes":{"wisdom":10}}',
        )
        await seed_known_spells(fight.pool, player, ("divine_sacred_flame",))
        state.architect_encounter["reaction_round"] = state.round_number
        await favor(fight)
        actions = [spell(player, "divine_sacred_flame", owner)]
        face = 10
    else:
        await fight.pool.execute(
            "INSERT INTO character_abilities (player_id, ability_id, equipped) VALUES ($1, $2, TRUE)",
            player,
            "warrior_unstoppable_charge",
        )
        actions = [spell(player, "warrior_unstoppable_charge", owner)]
        face = 10
    await fight.persist()
    rolls = []
    original = check_resolution_save.roll_participant_save

    def observe(participant, *args, **kwargs):
        result = original(participant, *args, **kwargs)
        rolls.append((participant.id, result))
        return result

    await fight.command("declare_phase", {"declarations": actions})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(face)) as d20s,
        patch("check_resolution_save.roll_participant_save", side_effect=observe),
        patch("dice.roll", return_value=_damage_die(4)),
    ):
        if route == "spell":
            offer = (await fight.command("resolve_phase", {}))["fate_offer"]
            assert (offer["roller_id"], offer["total"]) == (owner, face + 2)
            await reload_held(fight, await fight.reload())
        packets = await fight.drain()
    assert d20s.call_count == (2 if route == "floor" else 1)
    assert any(participant_id == owner for participant_id, _ in rolls), packets
    [saved] = [result for participant_id, result in rolls if participant_id == owner]
    assert (saved.roll, saved.modifier, saved.total, saved.dc, saved.success) == (face, 2, face + 2, face + 1, True)
    for participant_id, result in rolls:
        if participant_id != owner:
            assert result.modifier == 0


@pytest.mark.parametrize("fight", [((20, 20), "companion_kael")], indirect=True)
async def test_cathedral_resumes_each_victim_once_after_save_and_damage_holds(fight):
    discovered = discover(fight)
    assert discovered is not None
    owner, action = discovered
    player, edge = fight.players
    await favor(fight)
    await update_player_concentration(player, "divine_bless")
    fight.sd.concentration.spell_id = "divine_bless"
    state = await fight.reload()
    spatial = state.spatial
    spatial["positions"][edge] = pos(60)
    companion = next(actor for actor in state.participants if actor.type == "companion")
    spatial["positions"][companion.id] = pos(0, 5)
    for actor_id, location, hp, kind in (
        ("construct", pos(0, 0, 10), 20, "enemy"),
        ("above", pos(60, 0, 1), 20, "enemy"),
        ("dead", pos(5), 0, "enemy"),
        ("fallen", pos(10), 0, "companion"),
    ):
        actor = CombatParticipant(
            id=actor_id,
            name=actor_id,
            type=kind,
            initiative=1,
            hp_current=hp,
            hp_max=20,
            ac=14,
            is_dead=actor_id == "dead",
            is_fallen=hp == 0,
        )
        state.participants.append(actor)
        state.initiative_order.append(actor_id)
        spatial["positions"][actor_id] = location
        spatial["speeds"][actor_id] = 30
    state.get_participant("construct").damage_affinities = {"resistant": ["force"]}
    before_hp = companion.hp_current
    state.get_participant(edge).attributes["dexterity"] = 12
    await fight.persist()
    await fight.command("declare_phase", {"declarations": [strike(owner, player, action)]})
    await fight.command("resolve_phase", {})
    rolls = []
    original = check_resolution_save.roll_participant_save

    async def reload_party(state):
        members = fight.sd.party.members[1:]
        companion_state = fight.sd.companion
        await reload_held(fight, state)
        fight.sd.party.members.extend(members)
        fight.sd.companion = companion_state

    def observe(participant, *args, **kwargs):
        rolls.append(participant.id)
        return original(participant, *args, **kwargs)

    with (
        patch("check_resolution.dice_roll", side_effect=map(_d20, (2, 2, 20, 2, 2, 2))) as saves,
        patch("check_resolution_save.roll_participant_save", side_effect=observe),
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(8)) as damage,
    ):
        entry = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (entry["roll_kind"], entry["roller_id"]) == ("save", player)
        held = await fight.reload()
        assert held.get_participant(player).hp_current == 100
        assert held.get_participant(owner).action_ledger["cathedral"]["remaining"] == 0
        await reload_party(held)
        concentration = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (concentration["roll_kind"], concentration["roller_id"]) == ("save", player)
        held = await fight.reload()
        assert held.get_participant(player).hp_current == 92
        await reload_party(held)
        settled = await fight.command("resolve_phase", {})
        for victim in (edge, companion.id, "construct", "fallen"):
            offer = settled["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", victim)
            settled = await fight.command(
                "activate",
                {"id": offer["abilities"][0]["id"], "offer_id": offer["offer_id"], "keep": "original"},
            )
        cast = next(packet for packet in settled["packets"] if packet["actor_id"] == owner)
    roster_owner = next(participant for participant in settled["participants"] if participant["id"] == owner)
    spent = next(entry for entry in roster_owner["executable_actions"] if entry["id"] == action)
    assert not spent["available"] and spent["reason"] == "spent"
    results = {target["target_id"]: target for target in cast["targets"]}
    assert set(results) == {player, edge, companion.id, "construct", "fallen"}
    assert rolls == [target["target_id"] for target in cast["targets"]]
    assert saves.call_count == 6
    assert damage.call_args_list == [(("1d8",), {})] * 5
    assert all((result["save_type"], result["save_dc"]) == ("dexterity", 20) for result in results.values())
    assert results[edge]["save_success"] and results[edge]["damage"] == 0
    assert all(results[target]["damage_type"] == "force" for target in (player, companion.id, "construct"))
    state = await fight.reload()
    assert state.get_participant(player).hp_current == 92
    assert state.get_participant(edge).hp_current == 100
    assert state.get_participant(companion.id).hp_current == before_hp - 8
    assert state.get_participant("construct").hp_current == 16
    assert state.get_participant("above").hp_current == 20
    assert state.get_participant("fallen").death_save_failures == 1
    assert state.get_participant(owner).action_ledger["cathedral"]["remaining"] == 0
    assert sum(zone.get("kind") == "cathedral" for zone in state.spatial["zones"].values()) == 1
    with patch("check_resolution.dice_roll") as later:
        await play(fight, "above", move("above", pos(55, 0, 1)))
    later.assert_not_called()
    assert (await fight.reload()).get_participant("above").hp_current == 20


async def test_cathedral_collapses_in_the_lethal_transaction(fight, monkeypatch):
    owner = await cast_cathedral(fight)
    player = fight.players[0]
    state = await fight.reload()
    state.get_participant(owner).hp_current = 1
    spatial = state.spatial
    spatial["locations"]["kept"] = pos(3)
    spatial["zones"]["kept_zone"] = {"center_id": "kept", "radius_ft": 1}
    zone_id = next(key for key, value in spatial["zones"].items() if value.get("kind") == "cathedral")
    center_id = spatial["zones"][zone_id]["center_id"]
    await fight.persist()
    saved = []
    original = db_mutations.save_combat_state

    async def capture(combat_id, data, **kwargs):
        await original(combat_id, data, **kwargs)
        if data["architect_encounter"]["phase"] == "destroyed":
            saved.append(deepcopy(data))

    monkeypatch.setattr(db_mutations, "save_combat_state", capture)
    await fight.command("declare_phase", {"declarations": [attack(player, owner)]})
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await fight.drain()
    first = saved[0]
    assert zone_id not in first["spatial"]["zones"]
    assert center_id not in first["spatial"]["locations"]
    assert first["spatial"]["zones"]["kept_zone"] == {"center_id": "kept", "radius_ft": 1}
    assert first["spatial"]["locations"]["kept"] == pos(3)
    assert not first["spatial"]["structures"]
    assert fight.last_result["outcome"] == "victory"
    assert fight.last_result["xp_granted"] == 5000
    assert await db_mutations.load_combat_state(state.combat_id) is None
