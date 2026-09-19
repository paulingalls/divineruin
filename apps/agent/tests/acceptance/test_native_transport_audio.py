from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from acceptance._livekit import ensure_livekit_server
from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    count_audio_frames,
    mint_access_token,
    publish_audio_frames,
    wait_for_audio_track,
    wait_for_peer,
)

from native_transport_probe import build_tone_frames


def test_real_livekit_server_carries_the_deterministic_audio_track() -> None:
    async def exercise() -> None:
        server = ensure_livekit_server(require_docker=True)
        run_id = uuid.uuid4().hex
        room_name = f"native-audio-{run_id}"
        publisher_identity = f"publisher-{run_id}"
        receiver_identity = f"receiver-{run_id}"
        publisher = await connect_room(
            server.ws_url,
            mint_access_token(
                api_key=server.api_key,
                api_secret=server.api_secret,
                room_name=room_name,
                identity=publisher_identity,
            ),
        )
        receiver = None
        source = None
        try:
            receiver = await connect_room(
                server.ws_url,
                mint_access_token(
                    api_key=server.api_key,
                    api_secret=server.api_secret,
                    room_name=room_name,
                    identity=receiver_identity,
                ),
            )
            await asyncio.gather(
                wait_for_peer(publisher, identity=receiver_identity),
                wait_for_peer(receiver, identity=publisher_identity),
            )
            publish_task = asyncio.create_task(publish_audio_frames(publisher, build_tone_frames()))
            track = await wait_for_audio_track(receiver, identity=publisher_identity)
            assert await count_audio_frames(track) > 0
            source, _track, publication = await publish_task
            assert publication.sid
        finally:
            await aclose_audio(source)
            if receiver is not None:
                await aclose_room(receiver)
            await aclose_room(publisher)

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", [signal.SIGINT, signal.SIGTERM])
def test_probe_cancellation_closes_live_room_and_fixture(tmp_path: Path, kind: signal.Signals) -> None:
    async def exercise() -> None:
        run_id = uuid.uuid4().hex
        root = Path(__file__).resolve().parents[2]
        control = tmp_path / "control.json"
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            str(root / "native_transport_probe.py"),
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
        receiver = None
        try:
            async with asyncio.timeout(20):
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
                track = await wait_for_audio_track(receiver, identity=identity)
                assert await count_audio_frames(track) > 0
                child.send_signal(kind)
                _, stderr = await asyncio.wait_for(child.communicate(), 5)
                # See test_lifecycle: exit 1 without KeyboardInterrupt is what
                # separates the probe's own handler from the interpreter default.
                assert child.returncode == 1
                assert b"KeyboardInterrupt" not in stderr
                assert b"CancelledError" in stderr
                while identity in receiver.remote_participants:
                    await asyncio.sleep(0.02)
                async with httpx.AsyncClient() as client:
                    with pytest.raises(httpx.ConnectError):
                        await client.get(endpoint, params={"run_id": run_id})
        finally:
            if child.returncode is None:
                child.kill()
            await child.wait()
            if receiver is not None:
                await aclose_room(receiver)

    asyncio.run(exercise())
