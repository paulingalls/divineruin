"""Early prerequisite: two spoken commands require two authenticated audio turns."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import register_data_packet_collector
from acceptance._postgres_fixtures import _owned_postgres_container
from acceptance.choir_capstone_voice import BurstSTT, ChoirVoiceDiagnostic
from acceptance.multiplayer_voice._harness import PLAYER_TWO_SPEECH, MultiplayerVoiceHarness
from acceptance.seeds import seed_player_with_pools
from acceptance.voice_condition_harness import ScenarioModel

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
    "later_input,eager_model,drop_delivery",
    [(False, False, False), (True, False, False), (False, True, False), (True, False, True)],
)
async def test_later_command_requires_separate_authenticated_microphone_turn(
    later_input, eager_model, drop_delivery, livekit_server, reset_db_pool, monkeypatch
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
            if drop_delivery:
                monkeypatch.setattr("check_tools.publish_game_event", AsyncMock())
            await harness.play(harness.player_one_identity, PLAYER_TWO_SPEECH)
            await diagnostic.wait_for_receipts(2)
            diagnostic.assert_complete()
            receipt = list(diagnostic.model.receipts.values())[1]
            if drop_delivery:
                with pytest.raises(AssertionError, match="missing legal command gameplay event"):
                    await assert_legal_delivery(events, harness.listener.local_participant.identity, receipt, timeout=1)
            else:
                await assert_legal_delivery(events, harness.listener.local_participant.identity, receipt)
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


def stimulus_module():
    import importlib.util

    path = Path(__file__).resolve().parents[4] / "scripts/native-microphone-stimulus.py"
    spec = importlib.util.spec_from_file_location("native_microphone_stimulus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "listing",
    [
        "",
        "[0] Other Speakers, OtherDevice",
        "[0] MacBook Pro Speakers, BuiltInSpeakerDevice\n[1] MacBook Pro Speakers, BuiltInSpeakerDevice",
    ],
)
def test_stimulus_requires_one_exact_builtin_speaker(listing):
    stimulus = stimulus_module()
    assert stimulus.speaker_index("[7] MacBook Pro Speakers, BuiltInSpeakerDevice\n") == "7"
    with pytest.raises(RuntimeError, match="exactly one"):
        stimulus.speaker_index(listing)


@pytest.mark.parametrize(
    "url,run",
    [
        ("http://127.0.0.1:1234/fixture", "stale"),
        ("https://127.0.0.1:1234/fixture", "current"),
        ("http://example.com:1234/fixture", "current"),
        ("http://127.0.0.1/fixture", "current"),
        ("http://user:password@127.0.0.1:1234/fixture", "current"),
    ],
)
def test_stimulus_binds_status_to_owned_current_run(url, run):
    stimulus = stimulus_module()
    assert (
        stimulus.status_endpoint({"fixture_url": "http://127.0.0.1:1234/fixture", "run_id": "current"}, "current")
        == "http://127.0.0.1:1234/status?run_id=current"
    )
    with pytest.raises(RuntimeError, match="owned loopback"):
        stimulus.status_endpoint({"fixture_url": url, "run_id": run}, "current")


@pytest.mark.parametrize(
    "rate,width,channels,amplitude", [(24000, 2, 1, 12000), (48000, 1, 1, 100), (48000, 2, 2, 12000), (48000, 2, 1, 0)]
)
def test_stimulus_rejects_invalid_or_unvoiced_pcm(tmp_path, rate, width, channels, amplitude):
    import struct
    import wave

    path = tmp_path / "speech.wav"
    with wave.open(str(path), "wb") as output:
        output.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        output.writeframes((struct.pack("<h", amplitude) if width == 2 else b"\0") * rate * channels)
    with pytest.raises(RuntimeError, match="waveform"):
        stimulus_module().inspect_waveform(path)


def test_owned_acoustic_source_rejects_dm_tones_unrelated_bursts_and_wrong_run():
    import array
    import math

    from acceptance.choir_acoustic_source import AcousticSource, marker_pcm

    source = AcousticSource("current")

    def hear(pcm):
        samples = array.array("h", pcm)
        for start in range(0, len(samples), 480):
            source.observe(samples[start : start + 480], 48000)

    for frequency in (440, 1000):
        samples = array.array("h", (round(12000 * math.sin(2 * math.pi * frequency * n / 48000)) for n in range(48000)))
        hear(samples.tobytes())
        assert not source.receipts, "missing owned acoustic source guard"
    hear(marker_pcm("stale", 1))
    assert not source.receipts, "missing owned acoustic source guard"
    hear(marker_pcm("current", 1))
    assert source.receipts == [{"run_id": "current", "turn": 1, "source": "owned-acoustic-marker"}]
    hear(marker_pcm("current", 1))
    assert len(source.receipts) == 1, "replayed acoustic source advanced commands"
    hear(marker_pcm("current", 2))
    assert len(source.receipts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owned", "dm-tone", "unrelated-burst"])
async def test_acoustic_source_guard_on_real_authenticated_livekit(kind, livekit_server, reset_db_pool):
    import array

    from acceptance._livekit_client import play_audio_frames
    from acceptance.choir_acoustic_source import marker_pcm
    from acceptance.choir_capstone_voice import OwnedStimulusSTT
    from livekit import rtc

    from native_transport_probe import build_tone_frames

    harness = MultiplayerVoiceHarness(livekit_server)
    diagnostic = ChoirVoiceDiagnostic(harness.player_one_identity)
    speech = OwnedStimulusSTT("source-guard")

    async def prepare(room):
        await seed_player_with_pools(await db.get_pool(), player_id=harness.player_two_identity)
        await diagnostic.start(room)
        assert diagnostic.lifecycle is not None
        return diagnostic.lifecycle.authorize

    try:
        await harness.start(prepare, stt=speech)
        diagnostic.attach(harness.manager)
        audio = harness.audio[harness.player_one_identity][0]
        if kind == "owned":
            samples = array.array("h", marker_pcm("source-guard", 1, 16000))
            frames = [
                rtc.AudioFrame(samples[start : start + 160].tobytes(), 16000, 1, min(160, len(samples) - start))
                for start in range(0, len(samples), 160)
            ]
        elif kind == "dm-tone":
            frames = build_tone_frames()
        else:
            frames = PLAYER_TWO_SPEECH.frames()
        # The microphone source was created at 16kHz by the existing owned harness.
        if kind == "dm-tone":
            resampler = rtc.AudioResampler(48000, 16000)
            frames = [converted for frame in frames for converted in resampler.push(frame)] + resampler.flush()
        await play_audio_frames(audio, frames)
        if kind == "owned":
            try:
                await diagnostic.wait_for_receipts(1)
            except AssertionError as exc:
                raise AssertionError(
                    f"missing owned acoustic source/command: {[(source.observed_symbols, source.max_purity) for source in speech.sources]}"
                ) from exc
            await diagnostic.assert_refusal_unchanged()
            assert len(diagnostic.transcripts) == len(speech.source_receipts) == 1
        else:
            with pytest.raises(AssertionError, match="missing separate authenticated turn"):
                await diagnostic.wait_for_receipts(1, timeout=2)
            assert not speech.source_receipts and not diagnostic.transcripts and not diagnostic.model.calls
    finally:
        await diagnostic.aclose()
        await harness.aclose()


def test_stimulus_waits_for_five_current_microphone_frames_and_rejects_stale_status():
    stimulus = stimulus_module()
    healthy = iter([{"run_id": "current", "microphone_frames": 4}, {"run_id": "current", "microphone_frames": 5}])
    stimulus.wait_for_microphone("http://127.0.0.1:1234/status?run_id=current", "current", fetch=lambda: next(healthy))
    with pytest.raises(RuntimeError, match="another run"):
        stimulus.wait_for_microphone(
            "http://127.0.0.1:1234/status?run_id=current",
            "current",
            fetch=lambda: {"run_id": "stale", "microphone_frames": 5},
        )
    for frames in (0, 4, True):
        with pytest.raises(TimeoutError, match="microphone frames"):
            stimulus.wait_for_microphone(
                "http://127.0.0.1:1234/status?run_id=current",
                "current",
                fetch=lambda frames=frames: {"run_id": "current", "microphone_frames": frames},
                timeout=0.01,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
async def test_interrupt_owned_silent_probe_removes_children_endpoint_and_fixture(signal_name, reset_db_pool, tmp_path):
    from acceptance.choir_capstone_cleanup import interrupt_probe

    await interrupt_probe(signal_name, tmp_path)


def test_cleanup_fixture_rejects_audible_launch_before_execution(tmp_path):
    from acceptance.choir_capstone_cleanup import stimulus_command

    command = stimulus_command(tmp_path)
    assert command, "empty cleanup fixture command"
    forbidden = ("native-microphone-stimulus", "say", "audiotoolbox", "maestro", "simctl", "verify-native-build")
    assert not any(word in " ".join(command).lower() for word in forbidden), "audible cleanup fixture launch rejected"


@pytest.mark.parametrize("missing", ["probe", "stimulus", "descendant", "all"])
def test_cleanup_requires_the_complete_active_owned_family(missing, monkeypatch):
    from acceptance import choir_capstone_cleanup as cleanup

    monkeypatch.setattr(cleanup, "alive", lambda pid: True)
    owned = {"probe": 1, "stimulus": 2, "descendant": 3}
    cleanup.assert_active_family(owned)
    faulty = {} if missing == "all" else {key: pid for key, pid in owned.items() if key != missing}
    with pytest.raises(AssertionError, match="owned process family"):
        cleanup.assert_active_family(faulty)


@pytest.mark.parametrize("stopped", ["probe", "stimulus", "descendant"])
def test_cleanup_rejects_each_exited_owned_process(stopped, monkeypatch):
    from acceptance import choir_capstone_cleanup as cleanup

    owned = {"probe": 1, "stimulus": 2, "descendant": 3}
    monkeypatch.setattr(cleanup, "alive", lambda pid: pid != owned[stopped])
    with pytest.raises(AssertionError, match="cleanup fixture was not active"):
        cleanup.assert_active_family(owned)
