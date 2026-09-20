"""Persisted-state assertions for the representative Luna cases."""

from __future__ import annotations

import json
from typing import Any

from acceptance.strict_luna_scenarios import Scenario, _player_json
from livekit.agents.voice.run_result import FunctionCallOutputEvent

import db
import db_queries
import db_training


def successful_output(events: list[Any], call_id: str) -> str:
    matches = [e.item for e in events if isinstance(e, FunctionCallOutputEvent) and e.item.call_id == call_id]
    assert len(matches) == 1, f"expected one binder output for {call_id}, got {matches}"
    assert matches[0].is_error is False, f"tool binder rejected the call: {matches[0].output}"
    return matches[0].output


async def assert_case(case_id: str, scenario: Scenario, events: list[Any], call: Any | None) -> None:
    pool = await db.get_pool()
    sd = scenario.session_data
    if call is None:
        assert await _player_json(pool, sd.player_id) == scenario.before["player"]
        return
    output = successful_output(events, call.call_id)
    payload = json.loads(output) if output.strip().startswith(("{", "[")) else output

    if case_id == "exploration.query_inventory":
        assert "Healing Potion" in output, output
        after_player = await _player_json(pool, sd.player_id)
        assert after_player == scenario.before["player"], (scenario.before["player"], after_player)
    elif case_id == "exploration.check_gather":
        before = {row["id"]: row.get("quantity", 0) for row in scenario.before["inventory"]}
        raw_after = await pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id = $1", sd.player_id)
        after = {row["item_id"]: json.loads(row["data"]).get("quantity", 0) for row in raw_after}
        counts: dict[str, int] = {}
        for item_id in payload["materials"]:
            counts[item_id] = counts.get(item_id, 0) + 1
        assert counts and all(after[item_id] - before.get(item_id, 0) == count for item_id, count in counts.items())
    elif case_id == "exploration.travel":
        assert (await _player_json(pool, sd.player_id))["location_id"] == "greyvale_ruins_exterior"
    elif case_id.startswith("exploration.activate_"):
        assert payload["deducted"]
        assert await _player_json(pool, sd.player_id) != scenario.before["player"]
    elif case_id == "exploration.enter_combat":
        assert sd.combat_state is not None
        row = await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", sd.combat_state.combat_id)
        assert row is not None
    elif case_id == "combat.declare_multi_actor":
        row = await pool.fetchrow(
            "SELECT data FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"]
        )
        assert json.loads(row["data"])["beat"] == "resolution"
    elif case_id == "combat.resolve_phase":
        row = await pool.fetchrow(
            "SELECT data FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"]
        )
        assert row is not None and json.loads(row["data"])["round_number"] >= 1
    elif case_id == "combat.activate_reaction":
        assert sd.combat_state is not None and sd.combat_state.open_window is not None
        assert sd.combat_state.reactions_available[sd.player_id]["spent"] is True
        assert await _player_json(pool, sd.player_id) != scenario.before["player"]
    elif case_id == "combat.end_combat":
        row = await pool.fetchrow("SELECT 1 FROM combat_instances WHERE combat_id = $1", scenario.before["combat_id"])
        assert row is None and sd.combat_state is None
    elif case_id.startswith("dispatch.begin_"):
        rows = await db_training.get_player_training_activities(sd.player_id, conn=pool)
        assert len(rows) == 1 and rows[0]["state"] == "running_first_half"
    elif case_id == "dispatch.resolve_midpoint":
        rows = await db_training.get_player_training_activities(sd.player_id, conn=pool)
        assert len(rows) == 1 and rows[0]["state"] == "running_second_half"
    elif case_id == "onboarding.advance_beat":
        assert sd.onboarding_beat == 2
        assert (await _player_json(pool, sd.player_id))["flags"]["onboarding_beat"] == 2
    elif case_id == "blacksmith.repair_item":
        item = next(
            row
            for row in await db_queries.get_player_inventory(sd.player_id, conn=pool)
            if row["id"] == "shortsword_basic"
        )
        assert item["slot_info"]["current_hits"] == payload["restored_to"]
        assert (await _player_json(pool, sd.player_id))["gold"] < 100
    elif case_id == "creation.set_choice":
        assert sd.creation_state is not None and sd.creation_state.race == "draethar"
    elif case_id == "creation.finalize_character":
        assert await _player_json(pool, sd.player_id) is not None
    elif case_id == "exploration.enter_location":
        assert payload and await _player_json(pool, sd.player_id) == scenario.before["player"]
    elif case_id.startswith("exploration.check_"):
        assert payload
    elif case_id.startswith("dispatch.query_"):
        assert payload and await _player_json(pool, sd.player_id) == scenario.before["player"]
