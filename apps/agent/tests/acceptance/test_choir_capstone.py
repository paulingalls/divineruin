"""Mandatory real PostgreSQL/LiveKit Choir public-entry and search contract."""

import json

import pytest
from acceptance.choir_capstone_harness import ChoirEncounterDiagnostic
from acceptance.choir_capstone_voice import CHOIR_COMMAND_SPEECH, BurstSTT
from acceptance.multiplayer_voice._harness import MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.test_choir_capstone_guards import livekit_server as livekit_server
from acceptance.test_choir_capstone_guards import mandatory_services as mandatory_services
from acceptance.test_choir_capstone_guards import postgres_container as postgres_container

import db


@pytest.fixture
def mock_combat_agent_factory():
    return None


@pytest.mark.asyncio
async def test_committed_choir_entry_and_public_search(livekit_server, reset_db_pool):
    harness = MultiplayerVoiceHarness(livekit_server)
    encounter = ChoirEncounterDiagnostic(harness.player_one_identity)

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await encounter.start(room)
        return encounter.lifecycle.authorize

    async def speak():
        await harness.play(harness.player_one_identity, CHOIR_COMMAND_SPEECH)

    try:
        await harness.start(prepare, stt=BurstSTT())
        encounter.attach(harness.manager)
        receipt = await encounter.command(
            "enter_mode",
            {
                "mode": "combat",
                "encounter_id": "hollow_choir",
                "encounter_description": "Familiar voices hum, each a little wrong.",
            },
            speak,
        )
        assert not receipt.is_error
        entry = json.loads(receipt.output)
        assert entry["choir"]["phase"] == "search" and "voice" in entry["choir"]["cue"]
        receipt = await encounter.command("query_info", {"kind": "combat"}, speak)
        facts = json.loads(receipt.output)["choir"]
        assert facts["search_target_id"] == "choir_sound"
        action = next(action for action in facts["search_actions"] if action["skill"] == "arcana")
        assert action["dc"] == 18
        receipt = await encounter.command(
            "declare_phase",
            {
                "declarations": [
                    {"kind": "interact", "actor_id": encounter.player_id, "action": action["action"]},
                    {"kind": "defend", "actor_id": "choir_zone"},
                ]
            },
            speak,
        )
        assert not receipt.is_error, receipt.output
        await encounter.reload()
    finally:
        await encounter.aclose()
        await harness.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,key", [("spells", "arcane_bolt"), ("creatures", "hollow_choir"), ("encounter_templates", "hollow_choir")]
)
async def test_reseed_committed_content_repairs_stale_rows_and_rejects_omitted_seed(
    table, key, reset_db_pool, monkeypatch
):
    import asyncpg
    from acceptance.choir_capstone_harness import reseed_choir_content

    pool = await db.get_pool()
    original = json.loads(await pool.fetchval(f"SELECT data FROM {table} WHERE id=$1", key))
    stale = {**original, "name": "Stale pre-story fixture"}
    try:
        await pool.execute(f"UPDATE {table} SET data=$2::jsonb WHERE id=$1", key, json.dumps(stale))
        await reseed_choir_content(pool)
        assert json.loads(await pool.fetchval(f"SELECT data FROM {table} WHERE id=$1", key)) == original
        await pool.execute(f"UPDATE {table} SET data=$2::jsonb WHERE id=$1", key, json.dumps(stale))
        execute = asyncpg.Connection.executemany

        async def omit_table(conn, query, args, **kwargs):
            if query.startswith(f"INSERT INTO {table} "):
                return None
            return await execute(conn, query, args, **kwargs)

        with monkeypatch.context() as fault:
            fault.setattr(asyncpg.Connection, "executemany", omit_table)
            with pytest.raises(AssertionError, match=f"stale committed {table}"):
                await reseed_choir_content(pool)
    finally:
        await reseed_choir_content(pool)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["none", "drop-delivery", "leak-rollback"])
async def test_public_choir_encounter_requires_actual_gameplay_delivery(
    fault, livekit_server, reset_db_pool, monkeypatch
):
    import asyncio

    from acceptance._livekit_client import register_data_packet_collector
    from acceptance.choir_capstone_flow import ChoirCapstoneFlow

    import combat_init

    harness = MultiplayerVoiceHarness(livekit_server)
    encounter = ChoirEncounterDiagnostic(harness.player_one_identity)

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await encounter.start(room)
        return encounter.lifecycle.authorize

    async def speak():
        await harness.play(harness.player_one_identity, CHOIR_COMMAND_SPEECH)

    publish = combat_init.publish_game_event

    async def withhold_started(room, kind, *args, **kwargs):
        if kind != "combat_started":
            await publish(room, kind, *args, **kwargs)

    try:
        await harness.start(prepare, stt=BurstSTT())
        encounter.attach(harness.manager)
        assert harness.player_two is not None and harness.listener is not None
        events = asyncio.Queue()
        register_data_packet_collector(harness.player_two, topic="game_events", queue=events)
        flow = ChoirCapstoneFlow(encounter, speak, events, harness.listener.local_participant.identity)
        if fault == "drop-delivery":
            monkeypatch.setattr(combat_init, "publish_game_event", withhold_started)
            with pytest.raises(AssertionError, match="missing Choir gameplay delivery: combat_started"):
                await flow.run()
            assert encounter.sd.combat_state is not None and encounter.sd.combat_state.choir_encounter is not None
            assert encounter.sd.combat_state.choir_encounter["phase"] == "search"
            assert len(encounter.model.receipts) == 1
        elif fault == "leak-rollback":
            from combat_events import EventSink
            from game_events import publish_game_event

            emit = EventSink.emit

            async def leaking_emit(sink, room, kind, payload, **kwargs):
                await publish_game_event(room, kind, payload, **kwargs)
                await emit(sink, room, kind, payload, **kwargs)

            monkeypatch.setattr(EventSink, "emit", leaking_emit)
            with pytest.raises(AssertionError, match="rolled-back Choir phase leaked gameplay event"):
                await flow.run()
        else:
            await flow.run()
            import choir_scene
            import db_queries

            primary = await db_queries.get_player(encounter.player_id)
            guest = await db_queries.get_player(harness.player_two_identity)
            location = encounter.sd.location_id
            assert primary is not None and guest is not None
            receipt = choir_scene.read(primary, location)
            assert receipt is not None and receipt["status"] == "destroyed"
            assert choir_scene.read(guest, location) is None, "Choir receipt escaped primary owner"
            encounter.sd.location_id = "accord_market_square"
            assert choir_scene.read(primary, encounter.sd.location_id) is None
            entered = await flow.call(
                "enter_mode",
                {"mode": "combat", "encounter_id": "hollow_choir", "encounter_description": "Independent location"},
            )
            assert entered["choir"]["phase"] == "search", "destroyed source blocked another location"
            primary = await db_queries.get_player(encounter.player_id)
            assert primary is not None
            destroyed = choir_scene.read(primary, location)
            active = choir_scene.read(primary, encounter.sd.location_id)
            assert destroyed is not None and destroyed["status"] == "destroyed"
            assert active is not None and active["status"] == "combat"
    finally:
        await encounter.aclose()
        await harness.aclose()


def test_skipped_encounter_and_every_missing_checkpoint_fail_completion():
    from acceptance.choir_capstone_flow import STEPS, assert_complete

    healthy = {step: {"observed": True} for step in STEPS}
    assert_complete(healthy)
    for step in STEPS:
        missing = {key: value for key, value in healthy.items() if key != step}
        with pytest.raises(AssertionError, match="missing named Choir"):
            assert_complete(missing)
    with pytest.raises(AssertionError, match="missing named Choir"):
        assert_complete({})
    with pytest.raises(AssertionError, match="empty Choir"):
        assert_complete({step: {} for step in STEPS})


@pytest.mark.asyncio
async def test_committed_choir_aura_preserves_concentration_outside_radius(livekit_server, reset_db_pool):
    import asyncio

    from acceptance._livekit_client import register_data_packet_collector
    from acceptance.choir_capstone_flow import ChoirCapstoneFlow

    import db_mutations

    harness = MultiplayerVoiceHarness(livekit_server)
    encounter = ChoirEncounterDiagnostic(harness.player_one_identity)

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await encounter.start(room)
        return encounter.lifecycle.authorize

    async def speak():
        await harness.play(harness.player_one_identity, CHOIR_COMMAND_SPEECH)

    try:
        await harness.start(prepare, stt=BurstSTT())
        encounter.attach(harness.manager)
        assert harness.player_two is not None and harness.listener is not None
        events = asyncio.Queue()
        register_data_packet_collector(harness.player_two, topic="game_events", queue=events)
        flow = ChoirCapstoneFlow(encounter, speak, events, harness.listener.local_participant.identity)
        entry = await flow.call(
            "enter_mode",
            {"mode": "combat", "encounter_id": "hollow_choir", "encounter_description": "Outside-radius fixture"},
        )
        flow.owner = next(actor["id"] for actor in entry["participants"] if actor["type"] == "enemy")
        await flow.delivery("combat_started")
        state = await encounter.reload()
        assert state.spatial is not None
        # Spatial fixture only: the public phase still resolves the committed creature's aura.
        state.spatial["positions"][encounter.player_id] = {"x": 631, "y": 0, "z": 0}
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        await flow.declare(flow.ability(encounter.player_id, "arcane_detect_magic"))
        await flow.resolve()
        assert encounter.sd.member_state(encounter.player_id).concentration.spell_id == "arcane_detect_magic"
        await flow.declare()
        await flow.resolve(1)
        await encounter.reload()
        assert encounter.sd.member_state(encounter.player_id).concentration.spell_id == "arcane_detect_magic"
    finally:
        await encounter.aclose()
        await harness.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_committed_content_requires_nonempty_reachable_source(missing, reset_db_pool, monkeypatch):
    from pathlib import Path

    from acceptance.choir_capstone_harness import reseed_choir_content

    original = Path.read_text

    def source(path, *args, **kwargs):
        if path.name == "spells.json":
            if missing:
                raise FileNotFoundError("missing committed spells.json")
            return "[]"
        return original(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "read_text", source)
        with pytest.raises(FileNotFoundError if missing else AssertionError, match=r"committed spells\.json"):
            await reseed_choir_content(await db.get_pool())


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["silenced-command", "deafened-command"])
async def test_legal_choir_command_rejects_delivery_with_wrong_save_outcome(step):
    import asyncio
    from unittest.mock import AsyncMock

    from acceptance.choir_capstone_flow import ChoirCapstoneFlow

    receipt = {"save_type": "dexterity", "roll": 20, "total": 24, "outcome": "success"}
    flow = ChoirCapstoneFlow(None, None, asyncio.Queue(), "authenticated-agent")
    flow.call = AsyncMock(return_value=receipt)
    flow.remember = AsyncMock()
    delivery = flow.delivery

    async def bounded_delivery(kind, predicate=lambda event: True, timeout=5):
        return await delivery(kind, predicate, timeout=1)

    flow.delivery = bounded_delivery
    for success in (False, None, True):
        await flow.events.put(
            (
                json.dumps(
                    {
                        "type": "dice_roll",
                        "roll_type": "saving_throw",
                        "save_type": receipt["save_type"],
                        "roll": receipt["roll"],
                        "total": receipt["total"],
                        "success": success,
                    }
                ).encode(),
                "authenticated-agent",
            )
        )
        if success is True:
            await flow.legal_command(step)
            flow.remember.assert_awaited_once_with(step)
        else:
            with pytest.raises(AssertionError, match="missing Choir gameplay delivery: dice_roll"):
                await flow.legal_command(step)
            flow.remember.assert_not_awaited()
