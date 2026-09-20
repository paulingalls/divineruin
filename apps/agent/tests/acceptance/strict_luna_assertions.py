"""Persisted-state assertions for the representative Luna cases."""

from __future__ import annotations

import json
from typing import Any

from acceptance.strict_luna_scenarios import Scenario, _player_json
from livekit.agents.voice.run_result import FunctionCallOutputEvent

import db
import db_queries
import db_training

# An id no branch claims would be graded by nothing at all — a paid row that always passes.
STATE_BRANCHES = {
    "exploration.enter_location": "enter_location",
    "exploration.query_inventory": "query_inventory",
    "exploration.check_gather": "gather",
    "exploration.check_skill": "check_payload",
    "exploration.check_social": "check_payload",
    "exploration.check_discover": "check_payload",
    "exploration.check_save": "check_payload",
    "exploration.check_dice": "check_payload",
    "exploration.travel": "travel",
    "exploration.activate_self": "activate_cost",
    "exploration.activate_single": "activate_cost",
    "exploration.activate_multiple": "activate_cost",
    "exploration.enter_combat": "enter_combat",
    "exploration.conversation": "no_mutation",
    "combat.declare_multi_actor": "declared",
    "combat.resolve_phase": "resolved",
    "combat.activate_reaction": "reaction_spent",
    "combat.end_combat": "combat_cleared",
    "dispatch.query_training_programs": "query_unchanged",
    "dispatch.begin_physical_training": "training_started",
    "dispatch.begin_spell_training": "training_started",
    "dispatch.resolve_midpoint": "training_midpoint",
    "dispatch.conclude": "dispatch_concluded",
    "onboarding.advance_beat": "onboarding_beat",
    "blacksmith.repair_item": "repair",
    "creation.set_choice": "creation_choice",
    "creation.finalize_character": "creation_finalized",
}


def state_branch(case_id: str) -> str:
    """Name the persisted-state branch a case id selects, refusing an ungraded id."""
    branch = STATE_BRANCHES.get(case_id)
    if branch is None:
        raise AssertionError(f"{case_id}: no persisted-state assertion is routed for this case")
    return branch


async def _existing_player(pool, player_id: str) -> dict[str, Any]:
    player = await _player_json(pool, player_id)
    assert player is not None, f"no persisted player row for {player_id}"
    return player


def successful_output(events: list[Any], call_id: str) -> str:
    matches = [e.item for e in events if isinstance(e, FunctionCallOutputEvent) and e.item.call_id == call_id]
    assert len(matches) == 1, f"expected one binder output for {call_id}, got {matches}"
    assert matches[0].is_error is False, f"tool binder rejected the call: {matches[0].output}"
    return matches[0].output


async def assert_case(case_id: str, scenario: Scenario, events: list[Any], call: Any | None) -> None:
    branch = state_branch(case_id)
    pool = await db.get_pool()
    sd = scenario.session_data
    if call is None:
        assert await _player_json(pool, sd.player_id) == scenario.before["player"]
        return
    output = successful_output(events, call.call_id)
    payload: Any = json.loads(output) if output.strip().startswith(("{", "[")) else output

    if branch == "query_inventory":
        assert "Healing Potion" in output, output
        after_player = await _player_json(pool, sd.player_id)
        assert after_player == scenario.before["player"], (scenario.before["player"], after_player)
    elif branch == "gather":
        before = {row["id"]: row.get("quantity", 0) for row in scenario.before["inventory"]}
        raw_after = await pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id = $1", sd.player_id)
        after = {row["item_id"]: json.loads(row["data"]).get("quantity", 0) for row in raw_after}
        counts: dict[str, int] = {}
        for item_id in payload["materials"]:
            counts[item_id] = counts.get(item_id, 0) + 1
        assert counts and all(after[item_id] - before.get(item_id, 0) == count for item_id, count in counts.items())
    elif branch == "travel":
        assert (await _existing_player(pool, sd.player_id))["location_id"] == "greyvale_ruins_exterior"
    elif branch == "activate_cost":
        assert payload["deducted"]
        assert await _player_json(pool, sd.player_id) != scenario.before["player"]
    elif branch == "enter_combat":
        assert sd.combat_state is not None
        row = await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", sd.combat_state.combat_id)
        assert row is not None
    elif branch == "declared":
        row = await pool.fetchrow(
            "SELECT data FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"]
        )
        data = json.loads(row["data"])
        assert data["beat"] == "resolution"
        # The row's whole claim is that ONE call carried both actors; a player-only
        # declaration also reaches the resolution beat.
        assert set(data["pending_declarations"]) == {sd.player_id, "luna_enemy"}, data["pending_declarations"]
    elif branch == "resolved":
        row = await pool.fetchrow(
            "SELECT data FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"]
        )
        data = json.loads(row["data"])
        assert data["beat"] != "resolution", "the resolution beat was never consumed"
        assert (data["beat"], data["round_number"]) == (payload["beat"], payload["round"]), (data, payload)
    elif branch == "reaction_spent":
        assert sd.combat_state is not None and sd.combat_state.open_window is not None
        assert sd.combat_state.reactions_available[sd.player_id]["spent"] is True
        assert await _player_json(pool, sd.player_id) != scenario.before["player"]
    elif branch == "combat_cleared":
        row = await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"])
        assert row is None and sd.combat_state is None
    elif branch == "training_started":
        rows = await db_training.get_player_training_activities(sd.player_id, conn=pool)
        assert len(rows) == 1 and rows[0]["state"] == "running_first_half"
    elif branch == "training_midpoint":
        rows = await db_training.get_player_training_activities(sd.player_id, conn=pool)
        assert len(rows) == 1 and rows[0]["state"] == "running_second_half"
    elif branch == "dispatch_concluded":
        assert payload == {"status": "concluded_dispatch"}, payload
        assert sd.pre_dispatch_agent_type is None, sd.pre_dispatch_agent_type
        assert await _player_json(pool, sd.player_id) == scenario.before["player"]
    elif branch == "onboarding_beat":
        assert sd.onboarding_beat == 2
        assert (await _existing_player(pool, sd.player_id))["flags"]["onboarding_beat"] == 2
    elif branch == "repair":
        item = next(
            row
            for row in await db_queries.get_player_inventory(sd.player_id, conn=pool)
            if row["id"] == "shortsword_basic"
        )
        assert item["slot_info"]["current_hits"] == payload["restored_to"]
        assert (await _existing_player(pool, sd.player_id))["gold"] < 100
    elif branch == "creation_choice":
        assert sd.creation_state is not None and sd.creation_state.race == "draethar"
    elif branch == "creation_finalized":
        assert await _player_json(pool, sd.player_id) is not None
    elif branch == "enter_location":
        assert payload and await _player_json(pool, sd.player_id) == scenario.before["player"]
    elif branch == "check_payload":
        assert payload
    elif branch == "query_unchanged":
        assert payload and await _player_json(pool, sd.player_id) == scenario.before["player"]
    else:
        raise AssertionError(f"{case_id}: branch {branch!r} has no assertion body")
