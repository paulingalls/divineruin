from unittest.mock import AsyncMock

import pytest
from test_wire_contract import FIXTURE

import db_session_queries
from combat_ui_update import build_combat_ui_update
from session_data import CombatParticipant, CombatState

EVENTS = FIXTURE["events"]


@pytest.mark.parametrize("fixture_name,legacy", [("set", False), ("changed", False), ("clear", False), ("clear", True)])
async def test_session_init_projects_hp_and_the_stored_pool(monkeypatch, fixture_name, legacy):
    expected = EVENTS[f"temp_hp_session_{fixture_name}"]["character"]
    stored = dict(expected)
    if legacy:
        del stored["temp_hp"]
    for owner, name, result in [
        (db_session_queries.db_queries, "get_player_at_patron_revision", (stored, 0)),
        (db_session_queries.db_content_queries, "get_location", {"id": "accord"}),
        (db_session_queries.db_queries, "get_inventory_snapshot", {}),
        (db_session_queries.db_queries, "get_active_player_quests", []),
        (db_session_queries.db_activity_queries, "get_player_map_progress", {}),
        (db_session_queries.character_spells, "get_known", []),
    ]:
        monkeypatch.setattr(owner, name, AsyncMock(return_value=result))
    payload = await db_session_queries.get_session_init_payload(expected["player_id"])
    assert {key: payload["character"][key] for key in ("player_id", "hp", "temp_hp")} == {
        key: expected[key] for key in ("player_id", "hp", "temp_hp")
    }


@pytest.mark.parametrize("stage", ["changed", "clear"])
def test_combat_updates_project_the_current_player_pool(stage):
    event = EVENTS[f"temp_hp_combat_{stage}"]
    ally = next(row for row in event["combatants"] if row["id"] == "player_1")
    player = CombatParticipant(
        id="player_1",
        name=ally["name"],
        type="player",
        initiative=10,
        ac=14,
        hp_current=ally["hpCurrent"],
        hp_max=ally["hpMax"],
        temp_hp=ally["tempHp"],
        conditions=ally["conditions"],
    )
    state = CombatState(
        combat_id="temp-hp", participants=[player], initiative_order=[player.id], round_number=event["round"]
    )
    assert build_combat_ui_update(state) == {"round": event["round"], "combatants": [ally]}
