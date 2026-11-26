import json
from copy import deepcopy

import pytest
from _zhael_fate_fixtures import attack, defend
from combat._round_checkpoint_helpers import ORDINARY, Fight, checkpoint_fight, mock_combat_agent_factory  # noqa: F401

import architect_scene
import choir_scene
import combat_structures
import db_mutations
import dice
import lost_scout_scene
import still_scene

ENTRIES = (
    (ORDINARY, "greyvale_ruins_inner"),
    ("hollow_still", "ashmark_still"),
    ("hollow_architect", "ashmark_architect_works"),
    ("hollowed_scout", "greyvale_ruins_inner"),
    ("hollow_choir", "greyvale_ruins_inner"),
)


@pytest.mark.parametrize(("encounter", "location"), ENTRIES)
async def test_registered_entry_captures_committed_party(fight: Fight, encounter, location) -> None:
    await fight.prepare(location)
    if encounter == "hollowed_scout":
        await db_mutations.set_player_flag(fight.ids[0], f"{lost_scout_scene.TOKEN}.discovered", True)
    if encounter == "hollow_still":
        await db_mutations.set_player_flag(
            fight.ids[1],
            f"still_charm:{location}",
            json.dumps(dict(location_id=location, kind="paradise_trap", remaining_zone_hours=None)),
        )
    await fight.start(encounter)
    row = await fight.reload()
    assert [snapshot["round_number"] for snapshot in row["round_checkpoints"]] == [1]
    await fight.assert_snapshot(row)
    if encounter == "hollow_still":
        assert any(c["type"] == "charmed" for c in fight.session.combat_state.get_participant(fight.ids[1]).conditions)


async def test_registered_wrap_keeps_the_last_two_starts(fight: Fight) -> None:
    await fight.prepare("greyvale_ruins_inner", mage=True)
    await fight.start()
    first = (await fight.row())["round_checkpoints"][0]
    host, guest = fight.ids
    state = fight.session.combat_state
    foe = state.get_participant("mawling_1")
    state.spatial["positions"][host] = state.spatial["positions"][foe.id].copy()
    await fight.declare(
        attack(host, foe.id, state.get_participant(host).action_pool[0]["name"]),
        {**defend(guest), "kind": "ability", "action": "arcane_haste", "targets": [guest]},
        *[defend(p.id) for p in state.participants if p.type == "enemy"],
    )
    await fight.call("resolve_phase")
    partial = await fight.reload()
    assert partial["round_checkpoints"] == [first]
    assert partial["beat"] != "declaration"
    joiner = await fight.join()
    assert fight.session.combat_state.get_participant(joiner) is None
    await fight.finish_round(2)
    second = await fight.row()
    assert second["round_checkpoints"][0] == first
    await fight.assert_snapshot(second)
    flags = second["round_checkpoints"][-1]["players"]
    assert flags[host]["session_flags"]["weapon_used"]
    assert not flags[host]["session_flags"]["unbound_veil_mastery_used"]
    assert flags[guest]["session_flags"]["unbound_veil_mastery_used"]
    assert flags[guest]["data"]["focus"]["current"] < first["players"][guest]["data"]["focus"]["current"]
    assert flags[guest]["data"]["concentration"]
    assert flags[host]["data"]["resonance"]["current"] == first["players"][host]["data"]["resonance"]["current"] - 1
    assert joiner not in first["players"]
    assert joiner in flags
    await fight.declare(
        {"kind": "consume", "actor_id": guest, "item_id": "healing_potion_minor", "target_id": host},
        defend(host),
        *[defend(p.id) for p in fight.session.combat_state.participants if p.type == "enemy"],
    )
    await fight.finish_round(3)
    third = await fight.row()
    assert [snapshot["round_number"] for snapshot in third["round_checkpoints"]] == [2, 3]
    assert third["round_checkpoints"][0] == second["round_checkpoints"][-1]
    assert all("round_checkpoints" not in snapshot["combat"] for snapshot in third["round_checkpoints"])
    await fight.assert_snapshot(third)

    assert (
        next(
            slot["data"]["quantity"]
            for slot in third["round_checkpoints"][1]["players"][guest]["inventory"]
            if slot["item_id"] == "healing_potion_minor"
        )
        == 1
    )
    await fight.call("end_combat", outcome="fled")
    assert await db_mutations.load_combat_state(fight.combats[-1], conn=fight.pool) is None


@pytest.mark.parametrize(
    ("encounter", "location", "scene"),
    (
        ("hollow_choir", "greyvale_ruins_inner", choir_scene),
        ("hollow_still", "ashmark_still", still_scene),
        ("hollow_architect", "ashmark_architect_works", architect_scene),
    ),
)
async def test_retained_entry_owns_a_new_checkpoint(fight: Fight, encounter, location, scene, monkeypatch) -> None:
    await fight.prepare(location)
    await fight.start(encounter)
    state = fight.session.combat_state
    if scene is choir_scene:
        host = fight.ids[0]
        monkeypatch.setattr("check_resolution.dice_roll", lambda *a, **kw: dice.DiceResult("d20", [20], [], 20))
        await fight.declare(
            {"kind": "interact", "actor_id": host, "action": "choir_search_perception"},
            *[defend(p.id) for p in state.participants if p.id != host],
        )
    elif scene is still_scene:
        host, guest = fight.ids
        monkeypatch.setattr("check_resolution.dice_roll", lambda *a, **kw: dice.DiceResult("d20", [20], [], 20))
        await fight.declare({"kind": "interact", "actor_id": host, "action": "still_search_perception"}, defend(guest))
    else:
        await fight.declare()
    await fight.finish_round(2)
    if scene is still_scene:
        state = fight.session.combat_state
        anchor = state.still_encounter["revealed_ids"][0]
        state.spatial["positions"][host] = state.spatial["positions"][anchor].copy()
        await fight.declare(attack(host, anchor, state.get_participant(host).action_pool[0]["name"]), defend(guest))
        await fight.finish_round(3)
    before = await fight.row()
    assert len(before["round_checkpoints"]) == 2
    if scene is choir_scene:
        assert before["choir_encounter"]["phase"] == "exposed"
    elif scene is still_scene:
        assert before["still_encounter"]["illusion"] is not None
    else:
        architect = fight.session.combat_state.get_participant(before["architect_encounter"]["owner_id"])
        assert architect.legendary_capacity > 0
        architect.legendary_actions = 0
        state = fight.session.combat_state
        reaction_wall = f"{architect.id}_reaction_wall_{state.round_number}"
        combat_structures.add_wall(
            state, reaction_wall, "Architect's reaction wall", {"x": 5, "y": -3, "z": 0}, {"x": 5, "y": 3, "z": 0}
        )
        state.architect_encounter["structure_ids"].append(reaction_wall)
    await fight.call("end_combat", outcome="fled")
    assert await db_mutations.load_combat_state(before["combat_id"], conn=fight.pool) is None
    flags = json.loads(await fight.pool.fetchval("SELECT data FROM players WHERE player_id=$1", fight.ids[0]))["flags"]
    dormant = json.loads(flags[scene.key(location)])
    assert dormant["status"] == "dormant"
    assert "round_checkpoints" not in dormant.get("snapshot", {})
    await fight.start(encounter)
    after = await fight.reload()
    assert after["combat_id"] != before["combat_id"]
    assert [snapshot["round_number"] for snapshot in after["round_checkpoints"]] == [before["round_number"]]
    await fight.assert_snapshot(after)
    if scene is choir_scene:
        assert after["choir_encounter"]["phase"] == "exposed"
    elif scene is still_scene:
        assert after["still_encounter"]["illusion"] is None
    else:
        owner = fight.session.combat_state.get_participant(after["architect_encounter"]["owner_id"])
        assert owner.legendary_actions == owner.legendary_capacity == architect.legendary_capacity
        assert fight.session.combat_state.get_participant(reaction_wall).is_dead
        assert reaction_wall not in after["spatial"]["structures"]


async def test_legacy_gets_its_first_checkpoint_at_next_wrap(fight: Fight) -> None:
    await fight.prepare("greyvale_ruins_inner")
    await fight.start()
    row = await fight.row()
    del row["round_checkpoints"]
    await fight.write_row(row)
    await fight.reload()
    assert fight.session.combat_state.round_checkpoints == []
    await fight.declare()
    await fight.call("resolve_phase")
    await fight.reload()
    assert fight.session.combat_state.round_checkpoints == []
    await fight.finish_round(2)
    row = await fight.row()
    assert [snapshot["round_number"] for snapshot in row["round_checkpoints"]] == [2]
    await fight.assert_snapshot(row)


def _put(row: dict, path: tuple, value) -> None:
    for key in path[:-1]:
        row = row[key]
    row[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    (
        ((), None),
        ((), {}),
        ((0,), None),
        ((0, "combat_id"), "another_combat"),
        ((0, "round_number"), True),
        ((0, "round_number"), 0),
        ((0, "combat"), []),
        ((0, "combat", "round_checkpoints"), []),
        ((0, "combat", "combat_id"), "another_combat"),
        ((0, "combat", "round_number"), True),
        ((0, "combat", "round_number"), 2),
        ((0, "combat", "participants", 0), {}),
        ((0, "combat", "beat"), "narration"),
        ((0, "combat", "wrap_continuation"), {}),
        ((0, "players"), []),
        ((0, "players", "actor"), []),
        ((0, "players", "actor", "data"), []),
        ((0, "players", "actor", "data", "conditions"), []),
        ((0, "players", "actor", "data", "flags"), {"story": True}),
        ((0, "players", "actor", "data", "flags"), {"shadow_veil": True}),
        ((0, "players", "actor", "data", "flags"), {"encounter_concealment": True}),
        ((0, "players", "actor", "data", "flags"), {"concealed": True, "encounter_concealment": 1}),
        ((0, "players", "actor", "data", "flags"), []),
        ((0, "players", "actor", "session_flags"), []),
        ((0, "players", "actor", "session_flags"), {}),
        ((0, "players", "actor", "session_flags", "weapon_used"), 0),
        ((0, "players", "actor", "inventory"), {}),
        ((0, "players", "actor", "inventory", 0), []),
        ((0, "players", "actor", "inventory", 0), {"item_id": "longsword_guild"}),
        ((0, "players", "actor", "inventory", 0, "item_id"), ""),
        ((0, "players", "actor", "inventory", 0, "tainted"), 0),
        ((0, "players", "actor", "inventory", 0, "data"), []),
    ),
)
async def test_loader_refuses_a_corrupt_checkpoint(fight: Fight, path, value) -> None:
    await fight.prepare("greyvale_ruins_inner")
    await fight.start()
    row = await fight.row()
    path = tuple(fight.ids[0] if key == "actor" else key for key in path)
    _put(row, ("round_checkpoints", *path), value)
    await fight.write_row(row)
    with pytest.raises(ValueError, match="Malformed round checkpoint"):
        await fight.reload()


@pytest.mark.parametrize(
    "damage", ("too_many", "missing", "bad_id", "blank_combat_id", "future", "duplicate", "reversed", "gap")
)
async def test_loader_refuses_invalid_checkpoint_history(fight: Fight, damage) -> None:
    await fight.prepare("greyvale_ruins_inner")
    await fight.start()
    row = await fight.row()
    first = row["round_checkpoints"][0]
    second = deepcopy(first)
    second["round_number"] = second["combat"]["round_number"] = row["round_number"] = 3
    row["round_checkpoints"] = [second]
    match damage:
        case "too_many":
            row["round_checkpoints"] = [second, second, second]
        case "missing":
            del second["players"]
        case "bad_id":
            second["players"][""] = second["players"].pop(fight.ids[0])
        case "blank_combat_id":
            row["combat_id"] = second["combat_id"] = second["combat"]["combat_id"] = ""
        case "future":
            row["round_number"] = 2
        case "duplicate":
            row["round_checkpoints"] = [second, second]
        case "reversed":
            first["round_number"] = first["combat"]["round_number"] = 2
            row["round_checkpoints"] = [second, first]
        case "gap":
            row["round_checkpoints"] = [first, second]
    await fight.write_row(row)
    with pytest.raises(ValueError, match="Malformed round checkpoint"):
        await fight.reload()


async def test_wrap_fate_offer_keeps_the_previous_boundary(fight: Fight, monkeypatch) -> None:
    from conditions import apply_condition, has_condition

    await fight.prepare("greyvale_ruins_inner")
    host = fight.ids[0]
    await fight.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        host,
        json.dumps({"divine_favor": {"patron": "zhael", "level": 40, "max": 100}}),
    )
    fight.session.member_state(host).patron_id = "zhael"
    await fight.start()
    first = (await fight.row())["round_checkpoints"][0]
    state = fight.session.combat_state
    actor = state.get_participant(host)
    actor.conditions = apply_condition(actor.conditions, "frightened", source="mawling_1", duration=3)
    await fight.declare()
    await fight.call("resolve_phase")
    monkeypatch.setattr("check_resolution.dice_roll", lambda *args, **kwargs: dice.DiceResult("d20", [19], [], 19))
    held = (await fight.call("resolve_phase"))["fate_offer"]
    assert held["roll_kind"] == "save" and held["roller_id"] == host
    paused = await fight.reload()
    assert paused["round_number"] == 2 and paused["wrap_continuation"] is not None
    assert paused["round_checkpoints"] == [first]
    await fight.call("activate", id="zhael_fates_thread", offer_id=held["offer_id"], keep="original")
    await fight.finish_round(2)
    restored = await fight.reload()
    assert restored["round_checkpoints"][0] == first
    assert len(restored["round_checkpoints"]) == 2
    assert not has_condition(fight.session.combat_state.get_participant(host).conditions, "frightened")
    await fight.assert_snapshot(restored)
