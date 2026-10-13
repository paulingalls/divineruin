"""Early prerequisite: two spoken commands require two authenticated audio turns."""

import asyncio
import json

import pytest
from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import register_data_packet_collector
from acceptance._postgres_fixtures import _owned_postgres_container
from acceptance.choir_capstone_voice import BurstSTT, ChoirVoiceDiagnostic
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools

import db


async def assert_legal_delivery(events, sender_identity, receipt, timeout=5):
    result = json.loads(receipt.output)
    try:
        async with asyncio.timeout(timeout):
            while True:
                payload, sender = await events.get()
                assert sender == sender_identity
                event = json.loads(payload)
                if event["type"] == "transcript_entry":
                    continue
                assert event["type"] == "dice_roll" and event["roll_type"] == "saving_throw"
                assert all(event[field] == result[field] for field in ("save_type", "roll", "total"))
                assert event["success"] == (result["outcome"] == "success")
                return
    except TimeoutError as exc:
        raise AssertionError("missing legal command gameplay event") from exc


@pytest.fixture(scope="session")
def livekit_server():
    server = ensure_livekit_server(require_docker=True)
    return {"ws_url": server.ws_url, "api_key": server.api_key, "api_secret": server.api_secret}


@pytest.fixture(scope="session")
def postgres_container(livekit_server):
    with _owned_postgres_container() as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(autouse=True)
def mandatory_services(monkeypatch):
    monkeypatch.setenv("REQUIRE_DOCKER", "1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "later_input",
    [False, True],
)
async def test_later_command_requires_separate_authenticated_microphone_turn(
    later_input, livekit_server, reset_db_pool
):
    harness = MultiplayerVoiceHarness(livekit_server)
    diagnostic = ChoirVoiceDiagnostic(harness.player_one_identity)

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await diagnostic.start(room)
        assert diagnostic.lifecycle is not None
        return diagnostic.lifecycle.authorize

    try:
        await harness.start(prepare, stt=BurstSTT())
        assert harness.player_two is not None and harness.listener is not None
        events = asyncio.Queue()
        register_data_packet_collector(harness.player_two, topic="game_events", queue=events)
        diagnostic.attach(harness.manager)
        assert not diagnostic.model.calls
        await harness.play(harness.player_one_identity, PLAYER_TWO_SPEECH)
        await diagnostic.wait_for_receipts(1)
        await diagnostic.assert_refusal_unchanged()
        while not events.empty():
            payload, sender = events.get_nowait()
            assert json.loads(payload)["type"] == "transcript_entry", "silenced refusal published a gameplay effect"
            assert sender == harness.listener.local_participant.identity
        assert len(diagnostic.transcripts) == 1
        assert len(diagnostic.model.calls) == 1
        if later_input:
            await harness.play(harness.player_one_identity, PLAYER_TWO_SPEECH)
            await diagnostic.wait_for_receipts(2)
            diagnostic.assert_complete()
            receipt = list(diagnostic.model.receipts.values())[1]
            await assert_legal_delivery(events, harness.listener.local_participant.identity, receipt)
        else:
            await asyncio.sleep(2)
            assert len(diagnostic.model.calls) == 1
    finally:
        await diagnostic.aclose()
        await harness.aclose()
