"""Early prerequisite: two spoken commands require two authenticated audio turns."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import register_data_packet_collector
from acceptance._postgres_fixtures import _owned_postgres_container
from acceptance.choir_capstone_voice import BurstSTT, ChoirVoiceDiagnostic
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel

import db


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
@pytest.mark.parametrize("later_input,eager_model", [(False, False), (True, False), (False, True)])
async def test_later_command_requires_separate_authenticated_microphone_turn(
    later_input, eager_model, livekit_server, reset_db_pool
):
    harness = MultiplayerVoiceHarness(livekit_server)
    diagnostic = ChoirVoiceDiagnostic(harness.player_one_identity)
    if eager_model:
        diagnostic.model = ScenarioModel(diagnostic.model.commands)

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
        await diagnostic.wait_for_receipts(2 if eager_model else 1)
        if eager_model:
            assert len(diagnostic.transcripts) == 1
            assert len(diagnostic.model.calls) == len(diagnostic.model.receipts) == 2
            with pytest.raises(AssertionError, match="missing separate authenticated turn"):
                diagnostic.assert_complete()
            return
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
            async with asyncio.timeout(5):
                payload, sender = await events.get()
            assert payload and sender == harness.listener.local_participant.identity
        else:
            await asyncio.sleep(2)
            assert len(diagnostic.model.calls) == 1
            with pytest.raises(AssertionError, match="missing separate authenticated turn"):
                diagnostic.assert_complete()
    finally:
        await diagnostic.aclose()
        await harness.aclose()


def test_native_probe_requires_service_and_cannot_write_success_without_docker(tmp_path):
    agent_root = Path(__file__).resolve().parents[2]
    result = tmp_path / "result.json"
    failed = subprocess.run(
        [
            sys.executable,
            str(agent_root / "choir_capstone_probe.py"),
            "--run-id",
            "service-fault",
            "--control",
            str(tmp_path / "control.json"),
            "--result",
            str(result),
        ],
        cwd=agent_root,
        env={**os.environ, "DOCKER_HOST": "unix:///tmp/divineruin-choir-missing-docker.sock", "REQUIRE_DOCKER": "0"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert failed.returncode != 0
    assert "Docker is required for acceptance tests but is unavailable" in failed.stderr
    assert not result.exists()


@pytest.mark.parametrize("kind", ["SIGINT", "SIGTERM"])
@pytest.mark.asyncio
async def test_native_command_probe_interrupt_closes_room_and_control(tmp_path, reset_db_pool, kind):
    import signal
    import uuid

    import httpx
    from acceptance._livekit_client import aclose_audio, aclose_room, connect_room, publish_audio_frames, wait_for_peer

    from native_transport_probe import build_tone_frames

    run_id = uuid.uuid4().hex
    root = Path(__file__).resolve().parents[2]
    control = tmp_path / "control.json"
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        str(root / "choir_capstone_probe.py"),
        "--run-id",
        run_id,
        "--control",
        str(control),
        "--result",
        str(tmp_path / "result.json"),
        cwd=root,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    receiver = source = None
    try:
        async with asyncio.timeout(25):
            while not control.exists():
                assert child.returncode is None
                await asyncio.sleep(0.02)
            endpoint = json.loads(control.read_text())["fixture_url"]
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint, params={"run_id": run_id})
                response.raise_for_status()
                fixture = response.json()
                receiver = await connect_room(fixture["ws_url"], fixture["token"])
                identity = f"python-{run_id}"
                await wait_for_peer(receiver, identity=identity)
                source, _, _ = await publish_audio_frames(receiver, build_tone_frames())
                while True:
                    status = await client.get(endpoint.replace("/fixture", "/status"), params={"run_id": run_id})
                    if status.json()["microphone_frames"] > 0:
                        break
                    await asyncio.sleep(0.02)
                child.send_signal(getattr(signal, kind))
                _, stderr = await asyncio.wait_for(child.communicate(), 8)
                assert child.returncode == 1 and b"CancelledError" in stderr
                assert b"KeyboardInterrupt" not in stderr
                while identity in receiver.remote_participants:
                    await asyncio.sleep(0.02)
                with pytest.raises(httpx.ConnectError):
                    await client.get(endpoint, params={"run_id": run_id})
        assert (tmp_path / "microphone-turns.json").is_file()
        assert not (tmp_path / "result.json").exists()
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()
        await aclose_audio(source)
        if receiver is not None:
            await aclose_room(receiver)
