import json
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import defend
from acceptance._capstone_helpers import _d20
from acceptance.test_architect_fight import (
    fight as fight,
)
from acceptance.test_architect_fight import (
    isolated_content_cache as isolated_content_cache,
)
from acceptance.test_architect_fight import (
    mock_combat_agent_factory as mock_combat_agent_factory,
)
from acceptance.test_architect_fight import pos
from acceptance.test_architect_terrain import declare, set_favor

import architect_scene
import combat_spatial
import db_mutations
import db_queries


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("record_owner", "missing its encounter record"),
        ("record_template", "missing its encounter record"),
        ("record_type", "Invalid Architect encounter record"),
        ("owner", "matching enemy owner"),
        ("owner_type", "matching enemy owner"),
        ("duplicate_owner", "matching enemy owner"),
        ("duplicate_owner_id", "participant ID must be unique"),
        ("owner_identity", "matching enemy owner"),
        ("structure_type", "Invalid Architect structure IDs"),
        ("structure_empty", "Invalid Architect structure IDs"),
        ("structure_id_type", "Invalid Architect structure IDs"),
        ("duplicate_wall", "Duplicate Architect structure IDs"),
        ("unknown_wall", "identify a structure"),
        ("nonstructure", "identify a structure"),
        ("phase", "phase disagrees"),
        ("live_walls", "still owns live walls"),
        ("count_bool", "Invalid Architect Reshape budget"),
        ("count_three", "Invalid Architect Reshape budget"),
        ("future_round", "Invalid Architect Reshape budget"),
        ("missing_domain", "Invalid Architect domain"),
        ("domain_exclusion", "Invalid Architect domain"),
        ("invalid_floor", "Invalid Architect section"),
        ("invalid_ceiling", "Invalid Architect ceiling"),
        ("orphan_floor", "Invalid Architect pit membership"),
        ("orphan_actor", "Invalid Architect pit membership"),
    ],
)
async def test_bad_architect_snapshot_cannot_load(fight, defect, reason):
    state = await fight.reload()
    data = state.to_dict()
    record = data["architect_encounter"]
    owner = next(p for p in data["participants"] if p["id"] == record["owner_id"])
    match defect:
        case "record_owner":
            data.pop("architect_encounter")
            data["encounter_id"] = "other"
        case "record_template":
            data.pop("architect_encounter")
            owner["creature_id"] = "other"
        case "record_type":
            data["architect_encounter"] = []
        case "owner":
            owner["creature_id"] = "other"
        case "owner_type":
            owner["type"] = "companion"
        case "duplicate_owner":
            data["participants"][-1]["creature_id"] = "hollow_architect"
        case "duplicate_owner_id":
            data["participants"].append({**owner, "creature_id": "other"})
        case "owner_identity":
            record["owner_id"] = "other"
        case "structure_type":
            record["structure_ids"] = "unknown"
        case "structure_empty":
            record["structure_ids"] = []
        case "structure_id_type":
            record["structure_ids"] = [42]
        case "duplicate_wall":
            record["structure_ids"].append(record["structure_ids"][0])
        case "unknown_wall":
            record["structure_ids"].append("missing")
        case "nonstructure":
            record["structure_ids"].append(owner["id"])
        case "phase":
            record["phase"] = "destroyed"
        case "live_walls":
            owner.update(hp_current=0, is_dead=True, is_fallen=True)
            record["phase"] = "destroyed"
        case "count_bool":
            record.update(reshape_round=1, reshape_count=True)
        case "count_three":
            record.update(reshape_round=1, reshape_count=3)
        case "future_round":
            record.update(reshape_round=state.round_number + 1, reshape_count=1)
        case "missing_domain":
            data["spatial"]["movement_areas"].clear()
        case "domain_exclusion":
            next(iter(data["spatial"]["movement_areas"].values()))["excluded_actor_ids"] = []
        case "invalid_floor":
            record["floors"]["floor"] = {"min": pos(0), "max": pos(21, 1)}
        case "invalid_ceiling":
            domain = next(iter(data["spatial"]["movement_areas"].values()))
            data["spatial"]["movement_areas"]["ceiling"] = {**domain, "kind": "low_ceiling"}
        case "orphan_floor":
            record["pits"][fight.players[0]] = "missing"
        case "orphan_actor":
            record["floors"]["floor"] = {"min": pos(0), "max": pos(5, 5)}
            record["pits"]["missing"] = "floor"
    await db_mutations.save_combat_state(state.combat_id, data)
    with pytest.raises(ValueError, match=reason):
        await db_mutations.load_combat_state(state.combat_id)


@pytest.mark.parametrize("pointer", [None, "another-combat"])
async def test_end_refuses_missing_or_conflicting_pointer(fight, pointer):
    state = await fight.reload()
    pid = fight.players[0]
    key = architect_scene.key(state.location_id)
    if pointer is None:
        await fight.pool.execute("UPDATE players SET data = data #- ARRAY['flags', $2] WHERE player_id = $1", pid, key)
    else:
        await db_mutations.set_player_flag(
            pid, key, json.dumps({"location_id": state.location_id, "status": "combat", "combat_id": pointer})
        )
    player_before = await db_queries.get_player(pid)
    failure = await fight.command("end_combat", {"outcome": "fled"}, error=True)
    assert "authoritative combat pointer" in failure or "internal error" in failure.lower()
    assert await db_queries.get_player(pid) == player_before
    assert (await fight.reload()).to_dict() == state.to_dict()


async def test_active_pointer_blocks_fresh_entry(fight):
    from acceptance.test_architect_fight import reopen

    state = await fight.reload()
    await reopen(fight)
    try:
        denial = await fight.command("enter_mode", {"mode": "combat", "encounter_id": state.encounter_id}, error=True)
        assert "active combat" in denial
        persisted = await db_mutations.load_combat_state(state.combat_id)
        assert persisted is not None and persisted.to_dict() == state.to_dict()
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


@pytest.mark.parametrize("defect", ["missing", "damage", "other_actor", "stray_fate", "stray_roll", "other_target"])
async def test_geometry_continuation_refuses_corruption(fight, defect):
    from unittest.mock import patch

    from acceptance.test_architect_fight import _d20, _damage_die, setup_held_attack

    await setup_held_attack(fight, "Geometry Strike")
    with (
        patch("check_resolution.dice_roll", return_value=_d20(19)),
        patch("dice.roll", return_value=_damage_die(4)),
    ):
        assert (await fight.command("resolve_phase", {}))["fate_offer"]["roll_kind"] == "save"
    state = await fight.reload()
    data = state.to_dict()
    head = data["held_actions"][0]
    owner = next(p for p in data["participants"] if p["id"] == head["actor_id"])
    match defect:
        case "missing":
            del head["architect_attack"]
        case "damage":
            head["architect_attack"]["damage"] = -1
        case "other_actor":
            player = next(p for p in data["participants"] if p["id"] == fight.players[0])
            head["actor_id"] = player["id"]
            head["execution_receipt"]["actor_id"] = player["id"]
            player["last_action_execution"] = head["execution_receipt"]
            player["action_pool"] = owner["action_pool"]
        case "stray_fate":
            head["fate_attack"] = {}
        case "stray_roll":
            head.update(roll={}, reaction_ac_bonus=0)
        case "other_target":
            head["declaration"]["target_id"] = "elsewhere"
            head["execution_receipt"]["target_id"] = "elsewhere"
            owner["last_action_execution"] = head["execution_receipt"]
    await db_mutations.save_combat_state(state.combat_id, data)
    with pytest.raises(ValueError, match="Architect attack continuation"):
        await db_mutations.load_combat_state(state.combat_id)


async def test_old_unrelated_snapshot_does_not_require_architect_data(fight):
    state = await fight.reload()
    data = state.to_dict()
    owner_id = data.pop("architect_encounter")["owner_id"]
    data["encounter_id"] = "ordinary"
    owner = next(p for p in data["participants"] if p["id"] == owner_id)
    owner["creature_id"] = "hollow_knight"
    owner.pop("legendary")
    owner["legendary_actions"] = 0
    data.pop("legendary_continuation")
    data.pop("legendary_sequence")
    await db_mutations.save_combat_state(state.combat_id, data)
    restored = await db_mutations.load_combat_state(state.combat_id)
    assert restored is not None and restored.architect_encounter is None


@pytest.mark.parametrize(
    "defect",
    ["wrong_section", "wrong_target", "wrong_receipt_kind", "inconsistent_budget", "missing_receipt", "missing_roll"],
)
async def test_malformed_reshape_receipts_refuse_reload(fight, defect):
    state = await fight.reload()
    owner, player = state.architect_encounter["owner_id"], fight.players[0]
    combat_spatial.place(state, player, pos(5))
    await fight.persist()
    await set_favor(fight, "zhael", 40)
    floor = {"kind": "open_floor", "min": pos(4, -1), "max": pos(6, 1)}
    await declare(fight, defend(player), {**defend(owner), "reshape": [floor]})
    await fight.command("resolve_phase", {})
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        assert "fate_offer" in await fight.command("resolve_phase", {})
    state = await fight.reload()
    data = state.to_dict()
    [receipt] = data["held_actions"][0]["reshape_receipts"]
    match defect:
        case "wrong_section":
            receipt["section_id"] = "missing"
        case "wrong_target":
            receipt["results"] = [{"target_id": "missing", "save_success": True}]
        case "wrong_receipt_kind":
            receipt["kind"] = "destroy_wall"
        case "inconsistent_budget":
            data["architect_encounter"].update(reshape_round=0, reshape_count=0)
        case "missing_receipt":
            del data["held_actions"][0]["reshape_receipts"]
        case "missing_roll":
            data["held_actions"][0]["roll_steps"]["reshape"].clear()
    await db_mutations.save_combat_state(state.combat_id, data)
    with pytest.raises(ValueError, match="Architect Reshape"):
        await db_mutations.load_combat_state(state.combat_id)
