from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.test_architect_fight import fight as fight
from acceptance.test_architect_fight import isolated_content_cache as isolated_content_cache
from acceptance.test_architect_fight import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_architect_fight import pos
from acceptance.test_architect_legendary import spend
from acceptance.test_architect_reshape import declare
from acceptance.test_architect_terrain import set_favor
from acceptance.test_still_anchors import fresh_session

import combat_spatial
import combat_structures
import db_mutations
from db_mutations_concentration import update_player_concentration


def translation(state, *, wall=None, delta: float = 10):
    wall = wall or state.architect_encounter["structure_ids"][0]
    return {
        "kind": "move_wall",
        "wall_id": wall,
        **{k: {**v, "y": v["y"] + delta} for k, v in state.spatial["structures"][wall].items()},
    }


async def test_spend_refuses_invalid_selections_and_insufficient_points(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    wall, ruined = state.architect_encounter["structure_ids"]
    combat_spatial.place(state, player, pos(15, 4))
    combat_structures.collapse_wall(state, state.get_participant(ruined))
    combat_structures.add_wall(state, "foreign", "Other wall", pos(50), pos(55))
    state = await fight.persist()
    valid = translation(state, wall=wall)
    distorted = {**valid, "end": {**valid["end"], "x": valid["end"]["x"] + 1}}
    cases = [
        (owner, "Construct Slam", player, [], "not a legendary action"),
        (owner, "", "", [], "not a legendary action"),
        (owner, "Geometry Strike", "", [], "requires a target"),
        (owner, "Geometry Strike", player, [valid], "empty reshape"),
        (owner, "Geometry Strike", "unknown", [], "Unknown target"),
        (player, "Geometry Strike", owner, [], "not a Boss"),
        (owner, "Shift Wall", player, [valid], "empty target"),
        (owner, "Shift Wall", "", [], "one reshape operation"),
        (owner, "Shift Wall", "", [valid, valid], "one reshape operation"),
        (owner, "Shift Wall", "", [{"kind": "destroy_wall", "wall_id": wall}], "move_wall"),
        (owner, "Shift Wall", "", [translation(state, delta=30.01)], "30 feet"),
        (owner, "Shift Wall", "", [distorted], "without reshaping"),
        (owner, "Shift Wall", "", [{**valid, "wall_id": ruined}], "live wall"),
        (owner, "Shift Wall", "", [translation(state, wall="foreign")], "owned by the Architect"),
    ]
    before = await fight.snapshot()
    publisher = fight.sd.room.local_participant.publish_data
    publisher.reset_mock()
    with patch("check_resolution.dice_roll", side_effect=AssertionError("refusal rolled dice")):
        for actor, action, target, operations, reason in cases:
            refusal = await spend(fight, actor, action, target=target, operations=operations, error=True)
            assert reason in refusal
    assert await fight.snapshot() == before
    publisher.assert_not_called()
    for remaining in (2, 1):
        shifted = await spend(fight, owner, "Shift Wall", operations=[translation(await fight.reload())])
        assert shifted["legendary_actions_remaining"] == remaining
    before = await fight.snapshot()
    publisher.reset_mock()
    with patch("check_resolution.dice_roll", side_effect=AssertionError("unaffordable spend rolled dice")):
        refused = await spend(fight, owner, "Geometry Strike", target=player, error=True)
    assert "costs 2" in refused and "1 remaining" in refused
    assert await fight.snapshot() == before
    publisher.assert_not_called()


async def test_reaction_reload_preserves_the_ordinary_queue(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    target = state.get_participant(player)
    target.reaction_ids = ["cleric_shield_of_faith"]
    target.has_reaction_ability = True
    combat_spatial.place(state, player, pos(15, 4))
    await fight.persist()
    await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []})
    refusal = await spend(fight, owner, "Geometry Strike", target=player, error=True)
    assert "resolve_phase" in refusal
    await fight.command("resolve_phase", {})
    await fight.pool.execute(
        """UPDATE players SET data=jsonb_set(data, '{class}', '"cleric"') WHERE player_id=$1""",
        player,
    )
    before = await fight.reload()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(16)) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
    ):
        held = await spend(fight, owner, "Geometry Strike", target=player)
        window = held["next"]["waiting_on"]
        assert window["stage"] == "pre_roll"
        assert held["legendary_actions_remaining"] == 1
        saved = await fight.reload()
        assert saved.held_actions[1:] == before.held_actions
        assert saved.get_participant(player).hp_current == 100
        assert d20.call_count == damage.call_count == 0
        assert "held" in await spend(fight, owner, "Shift Wall", operations=[translation(saved)], error=True)
        await fresh_session(fight, saved)
        await fight.command("activate", {"id": window["reactions"][0]["id"], "target_id": player})
        resolved = await fight.command("resolve_phase", {})
    d20.assert_called_once()
    damage.assert_called_once()
    [attack] = [packet for packet in resolved["packets"] if packet["actor_id"] == owner]
    assert attack["damage"] == 4
    after, [row] = await fight.snapshot()
    assert after["held_actions"] == before.held_actions
    assert after["pending_declarations"] == before.pending_declarations
    assert after["round_number"] == before.round_number
    assert after["legendary_continuation"] is None
    assert row["hp"]["current"] == 96


@pytest.mark.parametrize("resume", ["activate", "resolve_phase", "fresh"])
async def test_fate_floor_save_resumes_the_same_section(fight, resume):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    combat_spatial.place(state, player, pos(5))
    state.get_participant(player).attributes["dexterity"] = 10
    await fight.persist()
    await set_favor(fight, "zhael", 40)
    if resume != "resolve_phase":
        await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []})
        await fight.command("resolve_phase", {})
    ordinary = (await fight.reload()).held_actions
    floor = {"kind": "open_floor", "min": pos(4, -5), "max": pos(6, 5)}
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)) as d20,
        patch("architect_reshape.dice.roll", return_value=_damage_die(8)) as damage,
    ):
        held = await spend(fight, owner, "Reshape", operations=[floor])
        offer = held["fate_offer"]
        state = await fight.reload()
        [floor_id] = state.architect_encounter["floors"]
        assert state.architect_encounter["pits"] == {}
        assert held["legendary_actions_remaining"] == 1
        assert "held Fate" in await spend(fight, owner, "Shift Wall", operations=[translation(state)], error=True)
        for verb, arguments in (
            ("declare_phase", {"declarations": [{"kind": "defend", "actor_id": owner, "reshape": []}]}),
            ("end_combat", {"outcome": "fled"}),
        ):
            assert "held Fate" in await fight.command(verb, arguments, error=True)
        if resume == "fresh":
            await fresh_session(fight, state)
        if resume == "activate":
            resumed = await fight.command(
                "activate", {"id": "zhael_fates_thread", "offer_id": offer["offer_id"], "keep": "original"}
            )
        else:
            resumed = await fight.command("resolve_phase", {})
    d20.assert_called_once()
    damage.assert_called_once_with("2d6")
    [receipt] = resumed["packets"][0]["reshape"]
    assert receipt["section_id"] == floor_id
    [victim] = receipt["results"]
    assert victim["target_id"] == player and victim["damage"] == 8 and victim["prone"]
    state, [row] = await fight.snapshot()
    assert state["architect_encounter"]["pits"] == {player: floor_id}
    assert state["architect_encounter"]["reshape_count"] == 0
    assert list(state["architect_encounter"]["floors"]) == [floor_id]
    assert state["legendary_continuation"] is None and state["round_number"] == 1
    assert state["held_actions"] == ordinary
    assert resumed["legendary_actions_remaining"] == 1 and row["hp"]["current"] == 92


async def test_automatic_geometry_damage_is_not_reapplied_after_fate(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    state.get_participant(player).reaction_ids = []
    combat_spatial.place(state, player, pos(15, 5))
    await fight.persist()
    await set_favor(fight, "zhael", 40)
    await update_player_concentration(player, "divine_bless")
    fight.sd.concentration.spell_id = "divine_bless"
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)) as saves,
        patch("dice.roll", return_value=_damage_die(4)) as damage,
    ):
        held = await spend(fight, owner, "Geometry Strike", target=player)
        assert held["fate_offer"]["roll_kind"] == "save"
        saved = await fight.reload()
        assert saved.get_participant(player).hp_current == 96
        await fresh_session(fight, saved)
        fight.sd.concentration.spell_id = "divine_bless"
        resumed = await fight.command("resolve_phase", {})
    saves.assert_called_once()
    damage.assert_called_once()
    [attack] = resumed["packets"]
    assert attack["automatic_hit"] and attack["damage"] == 4
    state, [row] = await fight.snapshot()
    assert state["legendary_continuation"] is None and state["round_number"] == 1
    assert resumed["legendary_actions_remaining"] == 1 and row["hp"]["current"] == 96


async def test_legendary_execution_commit_failure_keeps_combat_and_hp(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    state.get_participant(player).reaction_ids = []
    combat_spatial.place(state, player, pos(15, 5))
    await fight.persist()
    before = await fight.snapshot()
    publisher = fight.sd.room.local_participant.publish_data
    publisher.reset_mock()
    with (
        patch("dice.roll", return_value=_damage_die(4)) as damage,
        patch.object(db_mutations, "save_combat_state", side_effect=RuntimeError("failed to save legendary action")),
    ):
        await spend(fight, owner, "Geometry Strike", target=player, error=True)
    damage.assert_called_once()
    assert await fight.snapshot() == before
    publisher.assert_not_called()


async def test_held_legendary_snapshot_must_bind_to_spend_and_packet(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    combat_spatial.place(state, player, pos(15, 4))
    target = state.get_participant(player)
    target.reaction_ids = ["cleric_shield_of_faith"]
    target.has_reaction_ability = True
    await fight.persist()
    await spend(fight, owner, "Geometry Strike", target=player)
    state = await fight.reload()
    original = state.to_dict()
    for key, value in {
        "actor_id": player,
        "action_id": "Shift Wall",
        "execution_id": "other",
        "cost": 1,
        "remaining": 2,
        "round": 2,
    }.items():
        invalid = deepcopy(original)
        invalid["legendary_continuation"][key] = value
        await db_mutations.save_combat_state(state.combat_id, invalid)
        with pytest.raises(ValueError, match="legendary"):
            await db_mutations.load_combat_state(state.combat_id)
    [head] = original["held_actions"]
    tail = {key: value for key, value in head.items() if key != "legendary_kind"}
    tail["seq"] = 0
    window = original["open_window"]
    for field, value in (
        ("legendary_continuation", None),
        ("legendary_continuation", {**original["legendary_continuation"], "round": True}),
        ("legendary_sequence", -99),
        ("beat", "resolution"),
        ("ally_continuation", {}),
        ("wrap_continuation", {}),
        ("inner_fire_continuation", {}),
        ("held_actions", []),
        ("open_window", None),
        ("open_window", {**window, "id": "another-window"}),
        ("open_window", {**window, "actor_id": player}),
        ("open_window", {**window, "target_id": owner}),
        ("held_actions", [{**head, "actor_id": player}]),
        ("held_actions", [{**head, "seq": head["seq"] - 1}]),
        ("held_actions", [{**head, "legendary_kind": "reshape"}]),
        ("held_actions", [{**head, "opened": []}]),
        ("held_actions", [{**head, "declaration": {**head["declaration"], "action": "Construct Slam"}}]),
        ("held_actions", [{**head, "declaration": {**head["declaration"], "type": "defend"}}]),
        ("held_actions", [head, {**head, "seq": 0, "execution_id": "second-insert"}]),
        ("held_actions", [head, tail]),
        ("held_actions", [tail, head]),
    ):
        invalid = {**original, field: value}
        await db_mutations.save_combat_state(state.combat_id, invalid)
        with pytest.raises(ValueError, match=r"[Ll]egendary"):
            await db_mutations.load_combat_state(state.combat_id)
    await db_mutations.save_combat_state(state.combat_id, original)


async def test_declaration_keeps_the_earlier_legendary_reaction_spend(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    target = state.get_participant(player)
    target.reaction_ids = ["cleric_shield_of_faith"]
    target.has_reaction_ability = True
    combat_spatial.place(state, player, pos(15, 4))
    await fight.persist()
    await fight.pool.execute(
        """UPDATE players SET data=jsonb_set(data, '{class}', '"cleric"') WHERE player_id=$1""",
        player,
    )
    held = await spend(fight, owner, "Geometry Strike", target=player)
    window = held["next"]["waiting_on"]
    assert window["stage"] == "pre_roll"
    await fresh_session(fight, await fight.reload())
    assert "legendary action" in await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []}, error=True)
    assert "resolve_phase" in await fight.command("end_combat", {"outcome": "fled"}, error=True)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        await fight.command("activate", {"id": window["reactions"][0]["id"], "target_id": player})
        resumed = await fight.command("resolve_phase", {})
    assert resumed["next"]["verbs"] == ["declare_phase"]
    before = await fight.reload()
    reaction = before.reactions_available[player]
    assert reaction["spent"] and reaction["window_id"] == window["window_id"]
    await declare(fight, {"kind": "defend", "actor_id": owner, "reshape": []})
    assert (await fight.reload()).reactions_available[player] == reaction


async def test_existing_reaction_window_refuses_a_legendary_spend(fight):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    target = state.get_participant(player)
    target.reaction_ids = ["cleric_shield_of_faith"]
    target.has_reaction_ability = True
    combat_spatial.place(state, player, pos(15, 4))
    await fight.persist()
    await declare(
        fight,
        {
            "kind": "attack",
            "actor_id": owner,
            "target_id": player,
            "action": "Geometry Strike",
            "held_item_id": "",
            "rider": "",
            "reshape": [],
        },
    )
    await fight.command("resolve_phase", {})
    held = await fight.command("resolve_phase", {})
    assert held["next"]["waiting_on"]["stage"] == "pre_roll"
    before = await fight.snapshot()
    assert "resolve_phase" in await spend(fight, owner, "Shift Wall", operations=[translation(state)], error=True)
    assert await fight.snapshot() == before


@pytest.mark.parametrize("held_action", ["attack", "floor"])
async def test_fresh_ordinary_fate_checkpoint_refuses_insertion(fight, held_action):
    state = await fight.reload()
    owner = state.architect_encounter["owner_id"]
    player = fight.players[0]
    target = state.get_participant(player)
    target.reaction_ids = []
    target.attributes["dexterity"] = 10
    combat_spatial.place(state, player, pos(15, 4))
    await fight.persist()
    await set_favor(fight, "zhael", 40)
    if held_action == "attack":
        action = {
            "kind": "attack",
            "actor_id": owner,
            "target_id": player,
            "action": "Geometry Strike",
            "held_item_id": "",
            "rider": "",
            "reshape": [],
        }
    else:
        floor = {"kind": "open_floor", "min": pos(14, 2), "max": pos(16, 6)}
        action = {"kind": "defend", "actor_id": owner, "reshape": [floor]}
    await declare(fight, action)
    await fight.command("resolve_phase", {})
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        response = await fight.command("resolve_phase", {})
    assert response["fate_offer"]["roll_kind"] == ("attack" if held_action == "attack" else "save")
    state = await fight.reload()
    await fresh_session(fight, state)
    before = await fight.snapshot()
    assert "resolve_phase" in await spend(fight, owner, "Shift Wall", operations=[translation(state)], error=True)
    assert await fight.snapshot() == before


@pytest.mark.parametrize("selection", ["action", "target", "reshape"])
async def test_legacy_boss_refuses_an_unexecutable_action_selection(fight, selection):
    state = await fight.reload()
    owner = state.get_participant(state.architect_encounter["owner_id"])
    owner.legendary, owner.role, owner.legendary_actions = None, "boss", 1
    await fight.persist()
    before = await fight.snapshot()
    refused = await spend(
        fight,
        owner.id,
        "Geometry Strike" if selection == "action" else "",
        target=fight.players[0] if selection == "target" else "",
        operations=[translation(state)] if selection == "reshape" else [],
        error=True,
    )
    assert "requires empty action_id" in refused
    assert await fight.snapshot() == before
