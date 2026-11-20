from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from livekit.agents import Agent, AgentSession
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads

import architect_scene
import combat_spatial
import combat_structures
import db_mutations
import db_queries
import event_types as E
from check_resolution import D20Roll
from combat_agent import CombatAgent
from db_mutations_concentration import update_player_concentration
from db_mutations_resonance import read_player_resonance
from mode_tools import enter_mode
from movement_tools import move_player
from query_tools import query_info
from scene_tools import enter_location
from session_data import SessionData

STILL = "ashmark_still"
WORKS = "ashmark_architect_works"


@pytest.fixture(autouse=True)
def isolated_content_cache(monkeypatch):
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", f"architect_{uuid4().hex}:")


async def enter(harness: MawlingHarness):
    scene = await harness.command(enter_location.id, {"location_id": WORKS})
    entry = scene["architect"]
    assert entry["encounter_id"] == "hollow_architect"
    assert entry["entry"] == f'enter_mode(mode="combat", encounter_id="{entry["encounter_id"]}")'
    await harness.command(enter_mode.id, {"mode": "combat", "encounter_id": entry["encounter_id"]})
    assert isinstance(harness.session.current_agent, CombatAgent)
    state = await harness.reload()
    assert (state.location_id, state.encounter_id) == (WORKS, entry["encounter_id"])
    return state


@pytest.mark.parametrize("levels,warns", [((16, 16), True), ((17, 17), True), ((17, 18), False), ((18, 18), False)])
async def test_works_entry(reset_db_pool, levels, warns):
    harness = MawlingHarness()
    try:
        await harness.prepare(levels, companion=None, location=STILL, tools=(move_player,))
        scene = await harness.command(enter_location.id, {"location_id": STILL})
        destination = scene["location"]["exits"]["northwest"]["destination"]
        assert destination == WORKS
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(20)):
            moved = await harness.command(move_player.id, {"destination_id": destination})
            if levels == (18, 18):
                back = moved["location"]["exits"]["southeast"]["destination"]
                assert (await harness.command(move_player.id, {"destination_id": back}))["moved"]
                assert (await harness.command(move_player.id, {"destination_id": destination}))["moved"]
        assert moved["moved"]
        assert ("level 20" in moved.get("level_warning", "")) if warns else "level_warning" not in moved
        assert moved["location"]["exits"]["southeast"]["destination"] == STILL
        for pid in harness.players:
            row = await db_queries.get_player(pid)
            assert row is not None and row["location_id"] == WORKS
        state = await enter(harness)
        assert state.architect_encounter is not None
        owner = state.get_participant(state.architect_encounter["owner_id"])
        assert owner is not None and owner.creature_id == "hollow_architect"
        assert len(state.architect_encounter["structure_ids"]) == 2
    finally:
        await harness.close()


async def reopen(harness: MawlingHarness):
    await harness.session.aclose()
    if harness.sd.background is not None:
        await harness.sd.background.stop()
    harness.sd = SessionData(player_id=harness.players[0], location_id=WORKS, room=harness.sd.room)
    harness.session = AgentSession(llm=harness.model, max_tool_steps=5, userdata=harness.sd)
    await harness.session.start(
        Agent(instructions="Execute the command.", tools=[enter_mode, query_info, enter_location])
    )


@pytest.fixture
async def fight(reset_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((20,), companion=None, location=WORKS)
        await enter(harness)
        yield harness
    finally:
        await harness.close()


def pos(x: float, y: float = 0, z: float = 0):
    return {"x": x, "y": y, "z": z}


async def declare_attack(harness, actor, target, action):
    state = await harness.reload()
    await harness.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "attack",
                    "actor_id": actor,
                    "target_id": target,
                    "action": action,
                    "held_item_id": "",
                    "rider": "",
                },
                *[{"kind": "defend", "actor_id": p} for p in state.initiative_order if p != actor],
            ],
        },
    )


async def attack(harness, actor, target, action, *, face: int | None = 15, damage=4, action_dice=4):
    await declare_attack(harness, actor, target, action)
    d20 = (
        patch("check_resolution.dice_roll", side_effect=AssertionError("automatic hit prepared a d20"))
        if face is None
        else patch("check_resolution.dice_roll", return_value=_d20(face))
    )
    with (
        d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)) as rolled,
        patch("dice.roll", return_value=_damage_die(action_dice)) as extra,
    ):
        packets = await harness.drain()
    return next(p for p in packets if p["actor_id"] == actor), rolled, extra


async def test_flee_retains_damaged_owner_and_wall(fight):
    state = await fight.reload()
    record = state.architect_encounter
    owner_id, wall_id = record["owner_id"], record["structure_ids"][0]
    player_id = fight.players[0]
    combat_spatial.place(state, player_id, pos(13, 9))
    await fight.persist()
    for target in (owner_id, wall_id):
        summary, _, _ = await attack(fight, player_id, target, "Longsword", face=20)
        assert summary["damage"] > 0
    state = await fight.reload()
    south = record["structure_ids"][1]
    target = state.get_participant(south)
    assert target is not None
    target.hp_current = 1
    combat_spatial.place(state, player_id, pos(13, -9))
    await fight.persist()
    await attack(fight, player_id, south, "Longsword", face=20)
    before = await fight.reload()
    await fight.command("end_combat", {"outcome": "fled"})
    await reopen(fight)
    after = await enter(fight)
    assert before.round_number == after.round_number
    assert after.spatial is not None and before.spatial is not None
    for pid in (owner_id, wall_id, south):
        restored, saved = after.get_participant(pid), before.get_participant(pid)
        assert restored is not None and saved is not None
        assert restored.hp_current == saved.hp_current
        assert after.spatial["positions"][pid] == before.spatial["positions"][pid]
    assert before.spatial["structures"] == after.spatial["structures"]


@pytest.mark.parametrize("case", ["clear", "miss", "wall", "end", "beyond", "high", "off_path", "structure", "overlap"])
async def test_construct_slam(fight, case):
    state = await fight.reload()
    owner_id = state.architect_encounter["owner_id"]
    player_id = fight.players[0]
    combat_spatial.place(state, owner_id, pos(0))
    origin = (
        pos(3, 4, 4)
        if case == "clear"
        else pos(5, 0, 22)
        if case == "high"
        else pos(0)
        if case == "overlap"
        else pos(5)
    )
    if case == "high":
        combat_spatial.place(state, owner_id, pos(0, 0, 20))
    combat_spatial.place(state, player_id, origin)
    if case in {"wall", "end", "beyond", "high", "off_path", "structure"}:
        x = {"wall": 10, "end": 20, "beyond": 21, "high": 10, "off_path": 10, "structure": 5}[case]
        if case == "wall":
            combat_structures.add_wall(state, "far", "Far wall", pos(12, -2), pos(12, 2))
            state.get_participant(player_id).damage_affinities = {"resistant": ["bludgeoning"]}
        combat_structures.add_wall(state, "near", "Near wall", pos(x, 1 if case == "off_path" else -4), pos(x, 4))
    await fight.persist()
    target = "near" if case == "structure" else player_id
    summary, rolls, extra = await attack(fight, owner_id, target, "Construct Slam", face=1 if case == "miss" else 15)
    state = await fight.reload()
    if case == "overlap":
        assert not summary["resolved"] and "horizontal" in summary["reason"]
        assert rolls.call_count == extra.call_count == 0
    elif case == "miss":
        assert not summary["hit"] and state.get_participant(target).hp_current == 100
        assert state.spatial["positions"][target] == origin
        assert rolls.call_count == extra.call_count == 0
    elif case == "structure":
        assert summary["hit"] and state.get_participant(target).hp_current == 22
        assert state.spatial["positions"][target] == pos(5)
    else:
        assert summary["hit"] and summary["bonus_damage_type"] == "force" and summary["bonus_damage"] == 4
        end = state.spatial["positions"][target]
        if case in {"wall", "end"}:
            assert summary["push"]["wall_id"] == "near"
            assert end == pytest.approx(pos(10 if case == "wall" else 20))
            assert not combat_structures.blocks_path(end, origin, state.spatial["structures"]["near"])
            assert extra.call_count == 1
            assert state.get_participant(target).hp_current == (92 if case == "wall" else 88)
        else:
            expected = pos(12, 16, 4) if case == "clear" else pos(20, 0, 22 if case == "high" else 0)
            assert end == pytest.approx(expected)
            assert state.get_participant(target).hp_current == 92
            assert extra.call_count == 0


@pytest.mark.parametrize("case", ["edge", "outside", "destroyed", "unrelated", "normal_hit"])
async def test_geometry_strike(fight, case):
    state = await fight.reload()
    record = state.architect_encounter
    owner, wall = record["owner_id"], record["structure_ids"][0]
    player = fight.players[0]
    combat_spatial.place(state, player, pos(15, 4.999 if case in {"outside", "normal_hit"} else 5))
    if case in {"destroyed", "unrelated"}:
        ruined = state.get_participant(wall)
        combat_structures.collapse_wall(state, ruined)
        if case == "unrelated":
            combat_structures.add_wall(state, "unowned", "Other wall", pos(15, 10), pos(35, 10))
    await fight.persist()
    fight.sd.room.local_participant.publish_data.reset_mock()
    summary, _, _ = await attack(
        fight, owner, player, "Geometry Strike", face=None if case == "edge" else 15 if case == "normal_hit" else 1
    )
    state = await fight.reload()
    assert state.get_participant(player).hp_current == (96 if case in {"edge", "normal_hit"} else 100)
    if case == "edge":
        assert summary["automatic_hit"] is True and "roll" not in summary
        assert not any(event["type"] == E.DICE_ROLL for event in published_payloads(fight.sd.room))
    else:
        assert summary["roll"] == (15 if case == "normal_hit" else 1)


async def test_lethal_hit_collapses_owned_walls_and_settles_once(fight, monkeypatch):
    state = await fight.reload()
    record = state.architect_encounter
    owner = record["owner_id"]
    player = fight.players[0]
    state.get_participant(owner).hp_current = 1
    await fight.pool.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player, '{"class":"mage"}')
    before_resonance = (await read_player_resonance(player))["current"]
    before_player = await db_queries.get_player(player)
    assert before_player is not None
    before_xp = before_player.get("xp", 0)
    already_destroyed = combat_structures.add_wall(state, "ruined", "Ruined wall", pos(30, 20), pos(30, 40))
    record["structure_ids"].append(already_destroyed.id)
    combat_structures.collapse_wall(state, already_destroyed)
    combat_spatial.place(state, player, pos(11))
    combat_structures.add_wall(state, "unrelated", "Other wall", pos(40, 0), pos(40, 20))
    await fight.persist()
    original = db_mutations.save_combat_state
    snapshots = []
    fail_once = True

    async def capture(combat_id, data, **kwargs):
        nonlocal fail_once
        await original(combat_id, data, **kwargs)
        if any(p["id"] == owner and p["hp_current"] == 0 for p in data["participants"]):
            snapshots.append(deepcopy(data))
            if fail_once:
                fail_once = False
                raise ToolError("Injected after lethal snapshot write")

    monkeypatch.setattr(db_mutations, "save_combat_state", capture)
    await declare_attack(fight, player, owner, "Longsword")
    before = await fight.snapshot()
    fight.sd.room.local_participant.publish_data.reset_mock()
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        failed = await fight.command("resolve_phase", {}, error=True)
        assert "Injected after lethal snapshot write" in failed
        assert await fight.snapshot() == before
        assert not published_payloads(fight.sd.room)
        await fight.command("resolve_phase", {})
        before_settlement = await fight.snapshot()
        fight.sd.room.local_participant.publish_data.reset_mock()
        delete = db_mutations.delete_combat_state

        async def fail_after_delete(combat_id, **kwargs):
            await delete(combat_id, **kwargs)
            raise ToolError("Injected after settlement delete")

        with patch.object(db_mutations, "delete_combat_state", fail_after_delete):
            failed = await fight.command("resolve_phase", {}, error=True)
            assert "Injected after settlement delete" in failed
        assert await fight.snapshot() == before_settlement
        assert not published_payloads(fight.sd.room)
        await fight.drain()
    assert snapshots
    collapse = snapshots[-1]
    assert set(collapse["spatial"]["structures"]) == {"unrelated"}
    assert collapse["architect_encounter"]["phase"] == "destroyed"
    for wall in (p for p in collapse["participants"] if p["id"] in record["structure_ids"]):
        assert wall["hp_current"] == 0 and wall["is_dead"] and wall["is_fallen"]
    assert fight.last_result["outcome"] == "victory"
    assert await db_mutations.load_combat_state(state.combat_id) is None
    assert fight.last_result["defeated_enemies"] == ["The Architect"]
    assert fight.last_result["xp_total"] == fight.last_result["xp_granted"] == 5000
    assert (await read_player_resonance(player))["current"] == before_resonance + 8
    assert fight.last_result["architect"]["cue"] == state.get_participant(owner).catalog_narration["death_cue"]
    row = await db_queries.get_player(player)
    assert row is not None and row["xp"] == before_xp + 5000
    scene_receipt = architect_scene.read(row, WORKS)
    assert scene_receipt is not None and scene_receipt["status"] == "destroyed"
    await reopen(fight)
    scene = await fight.command(enter_location.id, {"location_id": WORKS})
    assert scene["architect"] is None
    refusal = await fight.command(enter_mode.id, {"mode": "combat", "encounter_id": "hollow_architect"}, error=True)
    assert "destroyed" in refusal
    assert await db_queries.get_player(player) == row


async def setup_held_attack(fight, action):
    state = await fight.reload()
    owner, player = state.architect_encounter["owner_id"], fight.players[0]
    await fight.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
        player,
        '{"divine_favor":{"patron":"zhael","level":40,"max":100}}',
    )
    await update_player_concentration(player, "divine_bless")
    fight.sd.concentration.spell_id = "divine_bless"
    if action == "Construct Slam":
        combat_spatial.place(state, owner, pos(0))
        combat_spatial.place(state, player, pos(5))
        combat_structures.add_wall(state, "collision", "Collision wall", pos(10, -5), pos(10, 5))
    else:
        combat_spatial.place(state, player, pos(15, 5))
    await fight.persist()
    await declare_attack(fight, owner, player, action)
    await fight.command("resolve_phase", {})
    return owner, player


async def reload_held(fight, state):
    await fresh_session(fight, state)
    fight.sd.concentration.spell_id = "divine_bless"


async def test_construct_slam_resumes_base_and_collision_saves_once(fight):
    owner, player = await setup_held_attack(fight, "Construct Slam")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)) as d20s,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as base_dice,
        patch("dice.roll", return_value=_damage_die(4)) as collision_dice,
    ):
        attack_offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (attack_offer["roll_kind"], attack_offer["roller_id"]) == ("attack", owner)
        await reload_held(fight, await fight.reload())
        window = await fight.command("resolve_phase", {})
        assert window["next"]["waiting_on"]["stage"] == "post_roll"
        base_offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (base_offer["roll_kind"], base_offer["roller_id"]) == ("save", player)
        state = await fight.reload()
        assert state.get_participant(player).hp_current == 92
        assert state.spatial["positions"][player] == pos(5)
        assert collision_dice.call_count == 0
        await reload_held(fight, state)
        collision_offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (collision_offer["roll_kind"], collision_offer["roller_id"]) == ("save", player)
        state = await fight.reload()
        pushed = state.spatial["positions"][player]
        assert pushed == pytest.approx(pos(10))
        assert state.get_participant(player).hp_current == 88
        await reload_held(fight, state)
        resolved = await fight.command("resolve_phase", {})
        result = next(p for p in resolved["packets"] if p["actor_id"] == owner)
        assert result["damage"] == 8 and result["bonus_damage"] == 4 and result["collision"]["damage"] == 4
        assert base_dice.call_count == 2 and collision_dice.call_count == 1 and d20s.call_count == 3
        state = await fight.reload()
        assert state.get_participant(player).hp_current == 88 and state.spatial["positions"][player] == pushed
    await fight.command(
        "declare_phase", {"declarations": [{"kind": "move", "actor_id": player, "destination": pos(5)}]}
    )


async def test_geometry_strike_resumes_automatic_damage_after_target_moves(fight):
    owner, player = await setup_held_attack(fight, "Geometry Strike")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)) as d20s,
        patch("dice.roll", return_value=_damage_die(4)) as damage,
    ):
        offer = (await fight.command("resolve_phase", {}))["fate_offer"]
        assert (offer["roll_kind"], offer["roller_id"]) == ("save", player)
        state = await fight.reload()
        assert state.get_participant(player).hp_current == 96
        combat_spatial.place(state, player, pos(0))
        state = await fight.persist()
        await reload_held(fight, state)
        resolved = await fight.command("resolve_phase", {})
        result = next(p for p in resolved["packets"] if p["actor_id"] == owner)
        assert result["automatic_hit"] and result["damage"] == 4
        assert d20s.call_count == damage.call_count == 1
        assert (await fight.reload()).get_participant(player).hp_current == 96


@pytest.mark.parametrize("starts_near", [True, False])
async def test_geometry_strike_uses_position_after_pre_roll_window(fight, starts_near):
    state = await fight.reload()
    player_id = fight.players[0]
    owner_id = state.architect_encounter["owner_id"]
    player = state.get_participant(player_id)
    assert player is not None
    player.reaction_ids = ["cleric_shield_of_faith"]
    player.has_reaction_ability = True
    near, far = pos(15, 5), pos(15, 4)
    combat_spatial.place(state, player_id, near if starts_near else far)
    await fight.persist()
    await declare_attack(fight, owner_id, player_id, "Geometry Strike")
    await fight.command("resolve_phase", {})
    paused = await fight.command("resolve_phase", {})
    assert paused["next"]["waiting_on"]["stage"] == "pre_roll"
    state = await fight.reload()
    combat_spatial.place(state, player_id, far if starts_near else near)
    state = await fight.persist()
    await fresh_session(fight, state)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)) as d20s,
        patch("dice.roll", return_value=_damage_die(4)),
    ):
        resolved = await fight.command("resolve_phase", {})
    result = next(p for p in resolved["packets"] if p["actor_id"] == owner_id)
    assert d20s.call_count == int(starts_near)
    assert (result["hit"], result.get("automatic_hit")) == ((False, None) if starts_near else (True, True))


async def test_slam_landing_leaves_same_side_ally_a_clear_heal(reset_db_pool):
    from acceptance.seeds import seed_known_spells

    harness = MawlingHarness()
    try:
        await harness.prepare((20, 20), companion=None, location=WORKS)
        patient, healer = harness.players
        await harness.pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", healer, '{"class":"cleric"}'
        )
        await seed_known_spells(harness.pool, healer, ("divine_heal_wounds",))
        state = await enter(harness)
        assert state.architect_encounter is not None
        owner = state.architect_encounter["owner_id"]
        combat_spatial.place(state, owner, pos(0))
        combat_spatial.place(state, patient, pos(5))
        combat_spatial.place(state, healer, pos(7, 1))
        combat_structures.add_wall(state, "collision", "Collision wall", pos(10, -5), pos(10, 5))
        await harness.persist()
        summary, _, _ = await attack(harness, owner, patient, "Construct Slam")
        assert summary["push"]["wall_id"] == "collision"
        await harness.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "ability",
                        "actor_id": healer,
                        "action": "divine_heal_wounds",
                        "targets": [patient],
                        "argument_type": "",
                    }
                ]
            },
        )
        await harness.drain()
        affected = (await harness.reload()).get_participant(patient)
        assert affected is not None and affected.hp_current > 88
    finally:
        await harness.close()
