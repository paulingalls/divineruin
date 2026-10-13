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
async def test_public_choir_encounter_requires_actual_gameplay_delivery(livekit_server, reset_db_pool):
    import asyncio

    from acceptance._livekit_client import register_data_packet_collector
    from acceptance.choir_capstone_flow import ChoirCapstoneFlow

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
