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
    catalog_two = terrain == "forest" and race == "human"
    if catalog_two:
        cast_ids.append("primal_ice_storm")
    ward = race != "korath"
    focus = 2 if poor else sum(spells.get_spell(sid).focus_cost for sid in cast_ids) + (ward_cost or 5)
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
    assert persisted["current"] == (2 if catalog_two else generated)
    assert resonance_writes.await_count == (1 if generated else 0) + int(catalog_two)
    if catalog_two:
        assert casts[1]["resonance_generated"] == 2
    if goodberry:
        assert casts[1]["resonance_generated"] == 0
    cast_cost = sum(spells.get_spell(sid).focus_cost for sid in cast_ids)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("terrain", ["mountain", "missing_key", "unknown_terrain"])
async def test_combat_terrain_commands(terrain, livekit_server, reset_db_pool, monkeypatch, mock_combat_agent_factory):
    import random

    import combat_resolution
    import db_content_queries
    import db_mutations
    from combat_agent import CombatAgent

    mock_combat_agent_factory.side_effect = lambda **kwargs: CombatAgent(**kwargs)
    for key, field in (("LIVEKIT_URL", "ws_url"), ("LIVEKIT_API_KEY", "api_key"), ("LIVEKIT_API_SECRET", "api_secret")):
        monkeypatch.setenv(key, livekit_server[field])
    harness = MultiplayerVoiceHarness(livekit_server)
    pid, guest = harness.player_one_identity, harness.player_two_identity
    pool = await db.get_pool()
    await spells.load_spells()
    await racial_resonance.load_racial_resonance()
    location_id = "combat-terrain-" + uuid.uuid4().hex
    location = {"id": location_id, "name": "Command mountain", "region_type": "wilderness"}
    if terrain != "missing_key":
        location["terrain"] = terrain
    await pool.execute("INSERT INTO locations (id, data) VALUES ($1, $2::jsonb)", location_id, json.dumps(location))
    for player_id in (pid, guest):
        await seed_player_with_pools(
            pool, player_id=player_id, class_="druid", focus_current=20, known_spells=("primal_healing_touch",)
        )
        await pool.execute(
            "UPDATE players SET data = data || $2::jsonb WHERE player_id = $1",
            player_id,
            json.dumps({"level": 9, "race": "human", "location_id": location_id}),
        )
    sd = SessionData(player_id=pid, location_id=location_id)
    reader = AsyncMock(wraps=db_content_queries.get_location_terrain)
    saves = AsyncMock(wraps=db_mutations.save_combat_state)
    monkeypatch.setattr(db_content_queries, "get_location_terrain", reader)
    monkeypatch.setattr(db_mutations, "save_combat_state", saves)
    initiative = combat_resolution.roll_initiative
    monkeypatch.setattr(
        combat_resolution, "roll_initiative", lambda entries: initiative(entries, rng=random.Random(138))
    )
    commands = [
        (
            "enter_mode",
            {"mode": "combat", "encounter_id": "shadeling_cluster", "encounter_description": "Mountain fight."},
        )
    ]
    if terrain == "mountain":
        declarations = [
            {
                "kind": "ability",
                "actor_id": pid,
                "action": "primal_healing_touch",
                "targets": [pid],
                "argument_type": "",
            },
            *[{"kind": "defend", "actor_id": actor} for actor in (guest, "shadeling_1", "shadeling_2")],
        ]
        for _ in range(3):
            commands += [
                ("declare_phase", {"declarations": declarations}),
                ("resolve_phase", {}),
                ("resolve_phase", {}),
            ]
        commands += [("activate", {"id": "veil_ward"})]

    async def checkpoint(step, receipt):
        if terrain != "mountain":
            assert receipt.is_error and location_id in receipt.output and "terrain" in receipt.output.lower()
            assert sd.combat_state is None
            saves.assert_not_awaited()
            assert (
                await pool.fetchval(
                    "SELECT count(*) FROM combat_instances WHERE data->>'location_id' = $1", location_id
                )
                == 0
            )
            return
        assert not receipt.is_error, receipt.output
        state = sd.combat_state
        assert state is not None and state.location_id == location_id
        assert state.terrain == "mountain"
        reader.assert_awaited_once_with(location_id)
        saved = await db_mutations.load_combat_state(state.combat_id, conn=pool)
        assert saved is not None and saved is not state and saved.terrain == "mountain"
        if step == 1:
            assert {p.id for p in state.participants} == {pid, guest, "shadeling_1", "shadeling_2"}
            await pool.execute(
                "UPDATE locations SET data = jsonb_set(data, '{terrain}', $2::jsonb) WHERE id = $1",
                location_id,
                json.dumps("city"),
            )
            monkeypatch.setattr(db, "_cache_get", AsyncMock(return_value=None))
        elif receipt.name == "resolve_phase":
            payload = json.loads(receipt.output)
            expected = "narration" if step in (3, 6, 9) else "declaration"
            assert state.beat == expected and state.open_window is None
            persisted = await db_mutations_resonance.read_player_resonance(pid, conn=pool)
            assert persisted["current"] == (1 if expected == "narration" else 0)
            if expected == "narration":
                packet = next(p for p in payload["packets"] if p["actor_id"] == pid)
                assert packet["cast"]["resonance_generated"] == 1
            if step == 7:
                sd.combat_state = saved
        elif receipt.name == "activate":
            assert json.loads(receipt.output)["deducted"]["focus"] == 5
            assert saved.veil_ward is not None
            assert saved.veil_ward["source"] == "druid"
            assert await pool.fetchval("SELECT count(*) FROM veil_wards WHERE scope_id = $1", location_id) == 0
        row = await db_queries.get_player(pid)
        assert row is not None
        casts = sum(step >= threshold for threshold in (3, 6, 9))
        assert row["focus"]["current"] == 20 - 2 * casts - (5 if step == 11 else 0)

    model = ScenarioModel(commands, checkpoint=checkpoint)
    await run_voice_commands(
        harness, sd, model, ExplorationAgent(region_type="wilderness"), monkeypatch, require_hud=terrain == "mountain"
    )
    assert model.checked == len(commands)
