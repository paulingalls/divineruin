"""The Lost Scout through the registered search, scene, combat and report tools."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.lost_scout_harness import ENTRANCE, HALL, INNER, REPORT, SCOUT, TOKEN, ScoutHarness
from sample_fixtures import CONTENT_ROOT, published_payloads

import db
import db_mutations
import event_types as E
from check_tools import check
from choice_tools import select
from combat_agent import CombatAgent
from movement_tools import move_player
from npcs import parse_npc_row


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.fixture
async def scout(reset_db_pool, monkeypatch):
    monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "_cache_set", AsyncMock())
    harness = ScoutHarness()
    await harness.prepare((4,), companion=None, location=ENTRANCE, tools=(check, select, move_player))
    await db_mutations.set_player_flag(harness.players[0], "veythar_seal_mark.discovered", True)
    monkeypatch.setattr("combat_end._build_handoff_agent", lambda *_: harness.explorer())
    try:
        yield harness
    finally:
        await harness.close()


async def test_token_and_optional_offer(scout):
    sources = {
        "content/locations.json": ("locations", ENTRANCE),
        "content/scenes.json": ("scenes", "scene_lost_scout"),
        "content/encounter_templates.json": ("encounter_templates", SCOUT),
        "content/creatures.json": ("creatures", SCOUT),
        "content/npcs.json": ("npcs", "guildmaster_torin"),
    }
    for filename, (table, row_id) in sources.items():
        authored = next(row for row in json.loads((CONTENT_ROOT / filename).read_text()) if row["id"] == row_id)
        saved = await scout.pool.fetchval(f"SELECT data FROM {table} WHERE id=$1", row_id)
        assert json.loads(saved) == authored
    before = await scout.scene()
    assert TOKEN not in json.dumps(before) and "Ressa Corrow" not in json.dumps(before)
    assert any("rubble" in feature for feature in before["location"]["key_features"])
    assert not (await scout.enter(INNER)).get("lost_scout")
    catalog = await scout.command("query_info", {"kind": "creature"})
    assert SCOUT not in {entry["id"] for entry in catalog["encounter_templates"]}
    await scout.enter(ENTRANCE)
    assert "lost_scout" not in await scout.flags()
    with patch("check_resolution.dice_roll", side_effect=AssertionError("token must not roll")):
        token = await scout.search(skill="perception")
    assert token["element_id"] == TOKEN and "Ressa Corrow" in token["description"]
    assert (await scout.flags())[f"{TOKEN}.discovered"] is True
    events = published_payloads(scout.sd.room)
    assert [event["element_id"] for event in events if event["type"] == E.HIDDEN_REVEALED] == [TOKEN]
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=20)):
        assert (await scout.search("research station"))["element_id"] == "ruins_journal_fragment"
    pid = scout.players[0]
    quest_row = "SELECT data FROM player_quests WHERE player_id=$1 AND quest_id='greyvale_anomaly'"
    await scout.pool.execute(
        "INSERT INTO player_quests (player_id,quest_id,data) VALUES ($1,'greyvale_anomaly',$2::jsonb)",
        pid,
        json.dumps({"current_stage": 6, "status": "active"}),
    )
    quest_before = await scout.pool.fetchval(quest_row, pid)
    before_inventory = await scout.pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id=$1", pid)
    assert (await scout.enter(INNER))["lost_scout"]["entry"]["encounter_id"] == SCOUT
    await scout.enter(ENTRANCE)
    assert await scout.pool.fetchval(quest_row, pid) == quest_before
    assert (
        await scout.pool.fetch("SELECT item_id, data FROM player_inventory WHERE player_id=$1", pid) == before_inventory
    )
    assert scout.sd.combat_state is None and not isinstance(scout.session.current_agent, CombatAgent)
    assert not any(event["type"] == E.COMBAT_STARTED for event in published_payloads(scout.sd.room))
    await scout.fresh_session()
    assert (await scout.enter(INNER))["lost_scout"]["entry"]["encounter_id"] == SCOUT


async def test_any_search_reveals_token_even_when_the_journal_roll_fails(scout):
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):
        result = await scout.search("research station")
    assert result["guaranteed_discovery"]["element_id"] == TOKEN
    assert result.get("element_id") != "ruins_journal_fragment"
    assert (await scout.enter(INNER))["lost_scout"]["entry"]["encounter_id"] == SCOUT


@pytest.mark.parametrize("outcome", ["withdrew", "fled", "fought"])
async def test_torin_reports_only_the_recorded_outcome(scout, outcome):
    await scout.stage_at(HALL)
    baseline = await scout.torin()
    other_query = {"kind": "npc", "target_id": "elder_yanna"}
    other_npc = await scout.command("query_info", other_query)
    assert "report_action" not in baseline
    await scout.command("select", REPORT, error=True)
    await scout.stage_at(ENTRANCE)
    if outcome == "withdrew":
        await scout.search()
        await scout.enter(INNER)
        await scout.enter(ENTRANCE)
    else:
        start = await scout.start_scout()
        assert "Tam" not in json.dumps(start)
        assert isinstance(scout.session.current_agent, CombatAgent)
        state = await scout.reload()
        assert state.encounter_id == SCOUT and state.get_participant("hollowed_scout_1") is not None
        await scout.command("end_combat", {"outcome": "fled" if outcome == "fled" else "defeat"})
        if outcome == "fled":
            # Walking out after a flight keeps the combat outcome; it is not a withdrawal.
            await scout.enter(ENTRANCE)
    await scout.command("select", REPORT, error=True)
    await scout.stage_at(HALL)
    offer = await scout.torin()
    assert offer["knowledge"] == baseline["knowledge"] and offer["report_action"] == REPORT
    if outcome == "withdrew":
        await scout.command("select", {**REPORT, "option": "fled"}, error=True)
    response = await scout.command("select", offer["report_action"])
    assert response["outcome"] == outcome
    assert "Ressa Corrow" in response["response"]
    row = json.loads(await scout.pool.fetchval("SELECT data FROM npcs WHERE id='guildmaster_torin'"))
    assert response["response"] == parse_npc_row(row["id"], row)["lost_scout_reports"][outcome]
    assert (await scout.torin())["knowledge"] == [*baseline["knowledge"], response["response"]]
    assert await scout.command("query_info", other_query) == other_npc
    await scout.fresh_session()
    assert await scout.command("select", REPORT) == response
    assert (await scout.torin())["knowledge"][-1] == response["response"]
    if outcome == "withdrew":
        await scout.stage_at(ENTRANCE)
        await scout.start_scout()
        await scout.command("end_combat", {"outcome": "fled"})
        await scout.stage_at(HALL)
        assert (await scout.torin())["knowledge"][-1] == response["response"]
        assert (await scout.command("select", REPORT))["outcome"] == "fled"
        assert (await scout.torin())["knowledge"][-1] == row["lost_scout_reports"]["fled"]


async def test_residue_once_across_a_real_reaction_hold_and_reentry(scout):
    await scout.pool.execute(
        """UPDATE players SET data=jsonb_set(data, '{class}', '"rogue"') WHERE player_id=$1""",
        scout.players[0],
    )
    await scout.start_scout()
    await scout.position_by_scout()
    await scout.declare_scout(scout.defend_action(), scout.attack_action(scout_attacks=True))
    await scout.reload()
    first = await scout.command("resolve_phase", {})
    cue = first["lost_scout_residue"]
    assert cue.count("Tam") == 1
    assert "younger brother in Millhaven" in cue and "no speaker tag or conversation" in cue
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=19)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=4)),
    ):
        held = await scout.command("resolve_phase", {})
        assert "rogue_uncanny_dodge" in {r["id"] for r in held["next"]["waiting_on"]["reactions"]}
        await scout.reload()
        combat = await scout.command("query_info", {"kind": "combat"})
        assert "Tam" not in json.dumps([held, combat])
        await scout.drain()
        assert "Tam" not in json.dumps(scout.last_result)
    await scout.command("end_combat", {"outcome": "fled"})
    await scout.enter(ENTRANCE)
    await scout.start_scout()
    await scout.declare_scout(scout.defend_action())
    assert "Tam" not in json.dumps(await scout.command("resolve_phase", {}))


async def test_first_round_kill_delivers_residue_and_clears_offer(scout):
    await scout.start_scout()
    await scout.position_by_scout()
    await scout.declare_scout(scout.attack_action())
    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=19)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=999)),
    ):
        receipts = [await scout.command("resolve_phase", {})]
        for _ in range(3):
            if scout.sd.combat_state is None:
                break
            receipts.append(await scout.command("resolve_phase", {}))
    assert receipts[-1]["outcome"] == "victory"
    assert sum("lost_scout_residue" in receipt for receipt in receipts) == 1
    assert not (await scout.scene()).get("lost_scout")
    await scout.command("enter_mode", {"mode": "combat", "encounter_id": SCOUT}, error=True)
