"""Terrain rules through microphone transport, public activate and real persistence."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel, assert_hud_floor, run_voice_commands

import ability_persistence
import db
import db_mutations_resonance
import db_mutations_veil_ward
import db_queries
import racial_resonance
import spells
from exploration_agent import ExplorationAgent
from session_data import SessionData

# terrain, catalog-1 generation, ward Focus cost (None means refusal)
TERRAINS = (
    ("ancient_forest", 1, 3),
    ("forest", 1, 5),
    ("grassland", 1, 5),
    ("mountain", 1, 5),
    ("coast", 1, 5),
    ("wetland", 1, 5),
    ("underground", 1, 5),
    ("farmland", 2, 5),
    ("village", 2, None),
    ("city", 3, None),
)
CASES = (
    [(terrain, "human", generated, cost) for terrain, generated, cost in TERRAINS]
    + [
        (terrain, "korath", generated, None)
        for terrain, generated in (("mountain", 0), ("underground", 0), ("forest", 0), ("coast", 1), ("wetland", 1))
    ]
    + [(terrain, "human", None, None) for terrain in ("unknown_terrain", "missing_key", "missing_row")]
    + [("ancient_forest", "poor_druid", None, None)]
)


@pytest.mark.asyncio
@pytest.mark.parametrize("terrain,race,generated,ward_cost", CASES)
async def test_terrain_commands(terrain, race, generated, ward_cost, livekit_server, reset_db_pool, monkeypatch):
    for key, field in (("LIVEKIT_URL", "ws_url"), ("LIVEKIT_API_KEY", "api_key"), ("LIVEKIT_API_SECRET", "api_secret")):
        monkeypatch.setenv(key, livekit_server[field])
    harness = MultiplayerVoiceHarness(livekit_server)
    pid, guest = harness.player_one_identity, harness.player_two_identity
    pool = await db.get_pool()
    await spells.load_spells()
    await racial_resonance.load_racial_resonance()
    location_id = "terrain-" + uuid.uuid4().hex
    if terrain != "missing_row":
        region = "city" if terrain in ("city", "village") else "dungeon" if terrain == "underground" else "wilderness"
        location = {"id": location_id, "name": "Command clearing", "region_type": region}
        if terrain != "missing_key":
            location["terrain"] = terrain
        await pool.execute("INSERT INTO locations (id, data) VALUES ($1, $2::jsonb)", location_id, json.dumps(location))
    invalid = terrain in ("unknown_terrain", "missing_key", "missing_row")
    poor = race == "poor_druid"
    goodberry = terrain == "city" or invalid
    cast_ids = [] if poor else ["primal_healing_touch"] + (["primal_goodberry"] if goodberry else [])
    ward = race != "korath"
    focus = 2 if poor else sum(2 if sid == "primal_healing_touch" else 1 for sid in cast_ids) + (ward_cost or 5)
    await seed_player_with_pools(pool, player_id=pid, class_="druid", focus_current=focus, known_spells=tuple(cast_ids))
    await seed_player_with_pools(pool, player_id=guest, class_="druid")
    await pool.execute(
        "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
        pid,
        json.dumps({"level": 9, "race": "human" if poor else race, "location_id": location_id}),
    )
    sd = SessionData(player_id=pid, location_id=location_id)
    model = ScenarioModel([("activate", {"id": sid}) for sid in cast_ids + (["veil_ward"] if ward else [])])
    resources = AsyncMock(wraps=ability_persistence.update_player_resources)
    resonance_writes = AsyncMock(wraps=db_mutations_resonance.update_player_resonance)
    ward_writes = AsyncMock(wraps=db_mutations_veil_ward.write_ward)
    monkeypatch.setattr(ability_persistence, "update_player_resources", resources)
    monkeypatch.setattr(db_mutations_resonance, "update_player_resonance", resonance_writes)
    monkeypatch.setattr(db_mutations_veil_ward, "write_ward", ward_writes)
    hud = await run_voice_commands(
        harness,
        sd,
        model,
        ExplorationAgent(region_type="wilderness"),
        monkeypatch,
        require_hud=not invalid and not poor,
    )
    outputs = list(model.receipts.values())
    assert all(output.name == "activate" for output in outputs)
    row = await db_queries.get_player(pid)
    assert row is not None
    persisted = await db_mutations_resonance.read_player_resonance(pid, conn=pool)
    if invalid or poor:
        assert all(output.is_error for output in outputs)
        for output in outputs:
            assert ("Focus" in output.output) if poor else ("terrain" in output.output.lower())
            if terrain in ("missing_key", "missing_row"):
                assert location_id in output.output
            elif invalid:
                assert terrain in output.output
        assert row["focus"]["current"] == focus and persisted["current"] == 0
        resources.assert_not_awaited()
        resonance_writes.assert_not_awaited()
        ward_writes.assert_not_awaited()
        return
    assert_hud_floor(hud)
    casts = [json.loads(output.output) for output in outputs[: len(cast_ids)]]
    assert all(not output.is_error for output in outputs[: len(cast_ids)])
    assert casts[0]["resonance_generated"] == generated
    assert persisted["current"] == generated
    assert resonance_writes.await_count == (1 if generated else 0)
    if goodberry:
        assert casts[1]["resonance_generated"] == 0
    cast_cost = 2 + int(goodberry)
    if ward:
        receipt = outputs[-1]
        if ward_cost is None:
            assert receipt.is_error and "natural" in receipt.output
            ward_writes.assert_not_awaited()
        else:
            assert not receipt.is_error
            assert json.loads(receipt.output)["deducted"]["focus"] == ward_cost
            assert ward_writes.await_count == 1
            assert await pool.fetchval("SELECT source FROM veil_wards WHERE scope_id = $1", location_id) == "druid"
    assert resources.await_count == len(cast_ids) + int(ward_cost is not None)
    assert row["focus"]["current"] == focus - cast_cost - (ward_cost or 0)
