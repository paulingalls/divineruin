"""Persisted geometry and public movement on real Postgres."""

import json
import subprocess
from copy import deepcopy
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _resolve_round
from acceptance._spatial_helpers import move, persisted, pos
from acceptance._spatial_helpers import spatial_entry as spatial_entry
from livekit.agents.llm import ToolError
from sample_fixtures import CONTENT_ROOT

import combat_turn
import db
import db_content_queries
import db_mutations
import db_queries
from combat_spatial import facts, validate_scene
from declaration_payloads import DefendDecl, MoveDecl
from mode_tools import _enter_mode_impl
from query_tools import _query_info_impl

TEMPLATES = json.loads((CONTENT_ROOT / "content/encounter_templates.json").read_text())
LEVELS = {
    "shadeling_cluster": 1,
    "ruins_mawling_pair": 5,
    "hollowed_scout": 4,
    "hollow_wisp": 2,
    "hollow_patrol_greyvale": 3,
    "ruins_guardian": 7,
    "bandit_ambush": 5,
    "ashmark_patrol": 6,
    "cult_cell": 8,
    "hollow_corrupted_settlement": 14,
}
MIGRATION = CONTENT_ROOT / "scripts/migrations/060_player_speed.sql"


async def test_speed_backfill_preserves_data_and_is_idempotent(spatial_entry):
    pool = await db.get_pool()
    originals = [
        {"name": "old", "sibling": {"nested": 1}},
        {"speed": 35, "other": 2},
        {"speed": 0},
        {"speed": "bad"},
        {"speed": None},
        ["nonobject"],
        "double encoded",
    ]
    ids = []
    for row in originals:
        _, players = await spatial_entry(row, enter=False)
        ids.append(players[0])
    await pool.execute(MIGRATION.read_text())
    expected = [{**originals[0], "speed": 30}, *originals[1:]]
    for pid, row in zip(ids, expected, strict=True):
        assert json.loads(await pool.fetchval("SELECT data FROM players WHERE player_id=$1", pid)) == row
    await pool.execute(MIGRATION.read_text())
    for pid, row in zip(ids, expected, strict=True):
        assert json.loads(await pool.fetchval("SELECT data FROM players WHERE player_id=$1", pid)) == row
    row = await db_queries.get_player(ids[0])
    assert row is not None and row["speed"] == 30


@pytest.mark.parametrize("speed", ["missing", None, True, "30", -1, "NaN"])
async def test_entry_refuses_missing_or_malformed_speed_after_migration(spatial_entry, speed):
    ctx, players = await spatial_entry(enter=False, members=2)
    pool = await db.get_pool()
    await pool.execute(MIGRATION.read_text())
    if speed == "missing":
        await pool.execute("UPDATE players SET data=data-'speed' WHERE player_id=$1", players[1])
    else:
        await pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{speed}', $2::jsonb) WHERE player_id=$1",
            players[1],
            json.dumps(speed),
        )
    before = await pool.fetchval("SELECT count(*) FROM combat_instances")
    with patch("combat_resolution.roll_initiative") as roll:
        with pytest.raises(ToolError, match="speed"):
            await _enter_mode_impl(ctx, "combat", "ruins_mawling_pair", "Invalid speed")
    roll.assert_not_called()
    assert ctx.userdata.combat_state is None
    assert ctx.userdata.room.local_participant.publish_data.call_count == 0
    assert await pool.fetchval("SELECT count(*) FROM combat_instances") == before


@pytest.mark.parametrize("migrated", [False, True])
async def test_created_and_migrated_speed_limits_movement(spatial_entry, migrated):
    ctx, players = await spatial_entry(enter=False)
    pool = await db.get_pool()
    if migrated:
        await pool.execute("UPDATE players SET data=data-'speed' WHERE player_id=$1", players[0])
        await pool.execute(MIGRATION.read_text())
    row = await db_queries.get_player(players[0])
    assert row is not None and row["speed"] == 30
    await _enter_mode_impl(ctx, "combat", "ruins_mawling_pair", "Move")
    state = ctx.userdata.combat_state
    pid = players[0]
    before = deepcopy(state.to_dict())
    with pytest.raises(ToolError, match="exceeds speed"):
        await combat_turn.declare_phase(
            ctx, [MoveDecl.model_validate({"kind": "move", "actor_id": pid, "destination": pos(30.0001)})]
        )
    assert ctx.userdata.combat_state.to_dict() == before
    assert (await persisted(state.combat_id)) == before
    payload = MoveDecl.model_validate({"kind": "move", "actor_id": pid, "destination": pos(30)})
    with pytest.raises(ToolError, match="more than once"):
        await combat_turn.declare_phase(ctx, [payload, DefendDecl(kind="defend", actor_id=pid)])
    declared = json.loads(await combat_turn.declare_phase(ctx, [payload]))
    assert declared["spatial"] == facts(ctx.userdata.combat_state, pid)
    with pytest.raises(ToolError, match="declaration beat"):
        await combat_turn._declare_phase_impl(ctx, {pid: move(pid, 60)})
    result = await _resolve_round(ctx)
    assert any(packet.get("moved_ft") == 30 for packet in result["packets"])
    saved = await db_mutations.load_combat_state(state.combat_id)
    assert saved is not None and saved.spatial is not None
    assert saved.spatial["positions"][pid] == pos(30)
    assert saved.spatial["speeds"][pid] == 30
    for actor_id in before["spatial"]["positions"]:
        if actor_id != pid:
            assert saved.spatial["positions"][actor_id] == before["spatial"]["positions"][actor_id]


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda row: row["id"])
async def test_actual_catalog_entry_persists_placement_and_zone_ids(spatial_entry, template, mock_combat_agent_factory):
    assert len(TEMPLATES) == 10 and {row["id"] for row in TEMPLATES} == set(LEVELS)
    assert any(row["scene_placement"]["zones"] for row in TEMPLATES)
    assert template["recommended_party_level"] == LEVELS[template["id"]]
    ctx, response = await spatial_entry(members=2, companion="companion_tam", encounter=template["id"])
    state = ctx.userdata.combat_state
    saved = await db_mutations.load_combat_state(state.combat_id)
    assert saved is not None and saved.spatial is not None
    assert saved.to_dict() == state.to_dict()
    scene = template["scene_placement"]
    assert set(saved.spatial["positions"]) == {p.id for p in state.participants}
    for pid in ctx.userdata.party.member_ids:
        assert saved.spatial["positions"][pid] == scene["party_start"]
    assert saved.spatial["positions"]["companion_tam"] == scene["companion_start"]
    assert saved.spatial["speeds"]["companion_tam"] == 35
    assert saved.spatial["locations"] == scene["locations"]
    assert saved.spatial["zones"] == scene["zones"]
    assert response["spatial"] == facts(saved, ctx.userdata.player_id)
    handoff = mock_combat_agent_factory.call_args.kwargs["chat_ctx"]
    assert any(
        json.dumps(response["spatial"]) in text
        for item in handoff.items
        for text in item.content
        if isinstance(text, str)
    )
    assert json.loads(await _query_info_impl(ctx, "combat")) == response["spatial"]


async def test_authored_zone_entry_and_actor_centered_membership(spatial_entry):
    pool = await db.get_pool()
    original = await db_content_queries.get_encounter_template("ruins_mawling_pair")
    assert original is not None
    authored = deepcopy(original)
    authored["scene_placement"]["locations"]["choir_core"] = pos(30)
    authored["scene_placement"]["zones"] = {
        "silence_sphere": {"center_id": "choir_core", "radius_ft": 5},
        "mawling_aura": {"center_id": "mawling_1", "radius_ft": 10},
    }
    try:
        await pool.execute(
            "UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", authored["id"], json.dumps(authored)
        )
        ctx, response = await spatial_entry()
        pid = ctx.userdata.player_id
        assert set(response["spatial"]["zones"]) == {"silence_sphere", "mawling_aura"}
        assert response["spatial"]["locations"]["choir_core"] == pos(30)
        await combat_turn._declare_phase_impl(ctx, {pid: move(pid)})
        await _resolve_round(ctx)
        saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
        assert saved is not None and saved.spatial is not None
        assert pid in facts(saved, pid)["zones"]["silence_sphere"]["members"]
    finally:
        await pool.execute(
            "UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", original["id"], json.dumps(original)
        )


@pytest.mark.parametrize("mutation", ["missing", "coverage", "point", "center", "radius", "collision"])
async def test_missing_or_invalid_placement_refuses_before_roll(spatial_entry, mutation):
    pool = await db.get_pool()
    original = await db_content_queries.get_encounter_template("ruins_mawling_pair")
    assert original is not None
    bad = deepcopy(original)
    scene = bad["scene_placement"]
    if mutation == "missing":
        del bad["scene_placement"]
    if mutation == "coverage":
        scene["actors"].pop("mawling_1")
    if mutation == "point":
        scene["party_start"]["x"] = True
    if mutation == "center":
        scene["zones"]["z"] = {"center_id": "unknown", "radius_ft": 1}
    if mutation == "radius":
        scene["zones"]["z"] = {"center_id": "mawling_1", "radius_ft": -1}
    if mutation == "collision":
        scene["locations"]["mawling_1"] = pos()
    ctx, _ = await spatial_entry(enter=False)
    before = await pool.fetchval("SELECT count(*) FROM combat_instances")
    try:
        await pool.execute("UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", bad["id"], json.dumps(bad))
        with patch("combat_resolution.roll_initiative") as roll:
            with pytest.raises(ToolError):
                await _enter_mode_impl(ctx, "combat", bad["id"], "Invalid placement")
        roll.assert_not_called()
        assert ctx.userdata.combat_state is None
        assert ctx.userdata.room.local_participant.publish_data.call_count == 0
        assert await pool.fetchval("SELECT count(*) FROM combat_instances") == before
    finally:
        await pool.execute(
            "UPDATE encounter_templates SET data=$2::jsonb WHERE id=$1", original["id"], json.dumps(original)
        )


@pytest.mark.parametrize("failure", ["after_move", "after_save"])
async def test_failed_phase_restores_positions_and_zones(spatial_entry, failure):
    ctx, _ = await spatial_entry()
    pid = ctx.userdata.player_id
    await combat_turn._declare_phase_impl(ctx, {pid: move(pid)})
    state = ctx.userdata.combat_state
    state.spatial["zones"]["actor_zone"] = {"center_id": pid, "radius_ft": 10}
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = deepcopy(state.to_dict())
    player_before = await db_queries.get_player(pid)
    calls = ctx.userdata.room.local_participant.publish_data.call_count
    original_packet = combat_turn._resolve_one_packet
    original_save = db_mutations.save_combat_state

    async def fail_packet(session, working, *args, **kwargs):
        await original_packet(session, working, *args, **kwargs)
        assert working.spatial["positions"][pid] == pos(30)
        working.spatial["zones"]["actor_zone"]["radius_ft"] = 99
        raise RuntimeError("injected after move")

    async def fail_save(combat_id, data, **kwargs):
        await original_save(combat_id, data, **kwargs)
        assert data["spatial"]["positions"][pid] == pos(30)
        raise RuntimeError("injected after save")

    target = "combat_turn._resolve_one_packet" if failure == "after_move" else "db_mutations.save_combat_state"
    with patch(target, side_effect=fail_packet if failure == "after_move" else fail_save):
        with pytest.raises(RuntimeError, match="injected"):
            await combat_turn._resolve_phase_impl(ctx)
    assert ctx.userdata.combat_state.to_dict() == before
    assert (await persisted(state.combat_id)) == before
    assert await db_queries.get_player(pid) == player_before
    assert ctx.userdata.room.local_participant.publish_data.call_count == calls


async def test_held_reload_uses_committed_positions(spatial_entry):
    ctx, _ = await spatial_entry()
    pid = ctx.userdata.player_id
    await combat_turn._declare_phase_impl(ctx, {pid: move(pid), "mawling_1": {"type": "defend"}})
    raw = await combat_turn._resolve_phase_impl(ctx)
    assert isinstance(raw, str)
    first = json.loads(raw)
    assert first["spatial"] == facts(ctx.userdata.combat_state, pid)
    assert first["spatial"]["positions"][pid] == pos(30)
    saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert saved is not None and saved.spatial is not None
    assert saved.held_actions
    saved.held_actions[0]["declaration"]["distance_ft"] = 999
    await db_mutations.save_combat_state(saved.combat_id, saved.to_dict())
    ctx.userdata.combat_state = await db_mutations.load_combat_state(saved.combat_id)
    assert ctx.userdata.combat_state is not None
    raw = await combat_turn._resolve_phase_impl(ctx)
    assert isinstance(raw, str)
    resumed = json.loads(raw)
    assert resumed["spatial"] == facts(ctx.userdata.combat_state, pid)
    assert resumed["spatial"]["distances_ft"]["mawling_1"] != 999
    assert json.loads(await _query_info_impl(ctx, "combat")) == resumed["spatial"]


async def test_held_movement_rechecks_committed_eligibility(spatial_entry):
    ctx, _ = await spatial_entry()
    await combat_turn._declare_phase_impl(ctx, {"mawling_1": move("mawling_1", 30)})
    await combat_turn._resolve_phase_impl(ctx)
    saved = await db_mutations.load_combat_state(ctx.userdata.combat_state.combat_id)
    assert saved is not None and saved.spatial is not None
    original = deepcopy(saved.spatial)
    enemy = saved.get_participant("mawling_1")
    assert enemy is not None
    enemy.conditions = [{"type": "restrained", "source": "test", "duration": 2}]
    await db_mutations.save_combat_state(saved.combat_id, saved.to_dict())
    ctx.userdata.combat_state = await db_mutations.load_combat_state(saved.combat_id)
    assert ctx.userdata.combat_state is not None
    result = await _resolve_round(ctx)
    assert any(p.get("resolved") is False for p in result["packets"])
    assert ctx.userdata.combat_state.spatial == original


@pytest.mark.parametrize("defect", ["bad_coordinate", "missing_destination", "unknown_target", "over_budget"])
async def test_corrupt_pending_and_held_destination_refuses_before_roll(spatial_entry, defect):
    for held in (False, True):
        ctx, _ = await spatial_entry()
        pid = "mawling_1" if held else ctx.userdata.player_id
        await combat_turn._declare_phase_impl(ctx, {pid: move(pid)})
        if held:
            await combat_turn._resolve_phase_impl(ctx)
        state = ctx.userdata.combat_state
        raw = state.held_actions[0]["declaration"] if held else state.pending_declarations[pid]
        if defect == "bad_coordinate":
            raw["destination"]["x"] = "bad"
        if defect == "missing_destination":
            raw["type"] = "MANEUVER"
            del raw["destination"]
        if defect == "unknown_target":
            raw["target_id"] = "missing"
        if defect == "over_budget":
            raw["destination"]["x"] = 999
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        before = await persisted(state.combat_id)
        spatial = deepcopy(state.spatial)
        calls = ctx.userdata.room.local_participant.publish_data.call_count
        with patch("check_resolution.dice_roll") as roll:
            with pytest.raises(ToolError):
                await combat_turn._resolve_phase_impl(ctx)
        roll.assert_not_called()
        assert ctx.userdata.combat_state.spatial == spatial
        if not held:
            # A refused stored declaration reopens the declaration beat; RESOLUTION would refuse forever.
            before = {**before, "beat": "declaration", "pending_declarations": {}}
        assert await persisted(state.combat_id) == before
        assert ctx.userdata.room.local_participant.publish_data.call_count == calls


def test_spatial_contract_parity_has_nonempty_floor():
    assert len(TEMPLATES) == 10
    assert any(row["scene_placement"]["zones"] for row in TEMPLATES)
    cases = []
    for row in TEMPLATES:
        cases.append((True, row))
        for mutate in (
            lambda s: s.pop("scene_placement"),
            lambda s: s["scene_placement"].pop("party_start"),
            lambda s: s["scene_placement"]["actors"].clear(),
            lambda s: s["scene_placement"]["party_start"].update(x=True),
            lambda s: s["scene_placement"]["party_start"].update(x="1"),
            lambda s: s["scene_placement"]["zones"].update(z={"center_id": "missing", "radius_ft": 1}),
            lambda s: s["scene_placement"]["zones"].update(z={"center_id": s["enemies"][0]["id"], "radius_ft": -1}),
            lambda s: s["scene_placement"]["zones"].update(z={"center_id": s["enemies"][0]["id"], "radius_ft": True}),
            lambda s: s["scene_placement"]["locations"].update({s["enemies"][0]["id"]: pos()}),
            lambda s: s["scene_placement"]["locations"].update({" ": pos()}),
            lambda s: s["scene_placement"]["party_start"].update(x=1e308),
        ):
            bad = deepcopy(row)
            mutate(bad)
            if bad.get("scene_placement", {}).get("party_start", {}).get("x") == 1e308:
                bad["scene_placement"]["locations"] = {"left": pos(1e308), "right": pos(-1e308)}
            cases.append((False, bad))
    expected = [valid for valid, _ in cases]
    python = []
    for _, row in cases:
        try:
            validate_scene(row)
            python.append(True)
        except ValueError:
            python.append(False)
    assert python == expected
    probe = """import { validateScenePlacement } from "./packages/shared/src/entities/encounter.ts";
const rows = await Bun.stdin.json();
console.log(JSON.stringify(rows.map(row => {
try { validateScenePlacement(row); return true; } catch { return false; }
})));"""
    result = subprocess.run(
        ["bun", "--eval", probe],
        input=json.dumps([row for _, row in cases]),
        text=True,
        capture_output=True,
        cwd=CONTENT_ROOT,
        check=True,
    )
    typescript = json.loads(result.stdout)
    assert len(typescript) == len(cases)
    assert all(isinstance(value, bool) for value in typescript)
    assert typescript == expected == python


@pytest.mark.parametrize("stage", ["declare", "resolve"])
@pytest.mark.parametrize("defect", ["missing_position", "negative_radius", "nonfinite_position"])
async def test_invalid_spatial_refuses_without_write(spatial_entry, stage, defect):
    ctx, _ = await spatial_entry()
    pid = ctx.userdata.player_id
    if stage == "resolve":
        await combat_turn._declare_phase_impl(ctx, {pid: {"type": "defend"}})
    state = ctx.userdata.combat_state
    before = await persisted(state.combat_id)
    if defect == "missing_position":
        state.spatial["positions"].pop(pid)
    if defect == "negative_radius":
        state.spatial["zones"]["invalid"] = {"center_id": pid, "radius_ft": -1}
    if defect == "nonfinite_position":
        state.spatial["positions"][pid]["x"] = float("inf")
    invalid = deepcopy(state.to_dict())
    events = ctx.userdata.room.local_participant.publish_data.call_count
    with patch("db_mutations.save_combat_state", wraps=db_mutations.save_combat_state) as save:
        with patch("check_resolution.dice_roll") as roll:
            with pytest.raises(ToolError):
                if stage == "declare":
                    await combat_turn._declare_phase_impl(ctx, {pid: {"type": "defend"}})
                else:
                    await combat_turn._resolve_phase_impl(ctx)
        roll.assert_not_called()
        save.assert_not_called()
    assert ctx.userdata.combat_state.to_dict() == invalid
    assert await persisted(state.combat_id) == before
    assert ctx.userdata.room.local_participant.publish_data.call_count == events


@pytest.mark.parametrize("data", [[], None, 17, "{}"])
async def test_entry_refuses_nonobject_or_double_encoded_data_after_migration(spatial_entry, data):
    ctx, players = await spatial_entry(enter=False)
    pool = await db.get_pool()
    await pool.execute(MIGRATION.read_text())
    await pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", players[0], json.dumps(data))
    with patch("combat_resolution.roll_initiative") as roll:
        with pytest.raises(ToolError):
            await _enter_mode_impl(ctx, "combat", "ruins_mawling_pair", "Corrupt data")
    roll.assert_not_called()
    assert ctx.userdata.combat_state is None
    assert ctx.userdata.room.local_participant.publish_data.call_count == 0
