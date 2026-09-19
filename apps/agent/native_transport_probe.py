from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import json
import math
import os
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from livekit import rtc

APP_ROOT = Path(__file__).resolve().parent
SESSION_INIT_FIXTURE = json.loads((APP_ROOT / "tests/native_transport/session_init_fixture.json").read_text())
SAMPLE_RATE = 48_000
FRAME_SAMPLES = 480
TONE_FRAMES = 200
TESTS_ROOT = APP_ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

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

import event_types as E
from game_events import publish_game_event


def build_tone_frames() -> list[rtc.AudioFrame]:
    frames = []
    for frame_index in range(TONE_FRAMES):
        start = frame_index * FRAME_SAMPLES
        samples = (
            round(12_000 * math.sin(2 * math.pi * 440 * (start + offset) / SAMPLE_RATE))
            for offset in range(FRAME_SAMPLES)
        )
        frames.append(
            rtc.AudioFrame(
                struct.pack(f"<{FRAME_SAMPLES}h", *samples),
                SAMPLE_RATE,
                1,
                FRAME_SAMPLES,
            )
        )
    return frames


def mint_probe_token(api_key: str, api_secret: str, room_name: str, identity: str) -> str:
    return mint_access_token(
        api_key=api_key,
        api_secret=api_secret,
        room_name=room_name,
        identity=identity,
        participant_kind="agent",
    )


def _positive_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def assert_mobile_result(result: dict[str, Any], run_id: str, publisher_identity: str) -> None:
    if result.get("run_id") != run_id:
        raise ValueError("mobile result run ID is stale")
    if not result.get("peer_ready") or not result.get("mobile_identity"):
        raise ValueError("mobile result is missing peer readiness")
    if result.get("publisher_identity") != publisher_identity:
        raise ValueError("mobile result names the wrong publisher")
    if result.get("subscribed_publisher_identity") != publisher_identity or not result.get("audio_track_sid"):
        raise ValueError("mobile result is missing the publisher audio subscription")
    if not _positive_count(result.get("packets_received")) or not _positive_count(result.get("bytes_received")):
        raise ValueError("mobile result has no received audio packets or bytes")
    if not result.get("event_received") or result.get("event_sender_identity") != publisher_identity:
        raise ValueError("mobile result has no current-run SESSION_INIT event")
    if result.get("hud_character") != "Upgrade Test Hero" or result.get("hud_location") != "Upgrade Test Room":
        raise ValueError("mobile result has incomplete HUD evidence")


def safe_result(result: dict[str, Any]) -> dict[str, Any]:
    forbidden = ("token", "secret", "credential")

    def contains_credential(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                any(word in str(key).lower() for word in forbidden) or contains_credential(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return any(contains_credential(child) for child in value)
        return False

    if contains_credential(result):
        raise ValueError("native transport result contains a credential field")
    return result


class ProbeState:
    def __init__(self, fixture: dict[str, str]) -> None:
        self.fixture = fixture
        self.microphone_frames = 0
        self.mobile_result: dict[str, Any] | None = None
        self.condition = threading.Condition()

    def set_microphone_frames(self, count: int) -> None:
        with self.condition:
            self.microphone_frames = count
            self.condition.notify_all()

    def set_mobile_result(self, result: dict[str, Any]) -> None:
        with self.condition:
            self.mobile_result = result
            self.condition.notify_all()


def make_handler(state: ProbeState, run_id: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _write(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _current_run(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            return query.get("run_id") == [run_id]

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if not self._current_run():
                self._write(409, {"error": "stale run ID"})
            elif path == "/fixture":
                self._write(200, state.fixture)
            elif path == "/status":
                self._write(200, {"run_id": run_id, "microphone_frames": state.microphone_frames})
            else:
                self._write(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/result" or not self._current_run():
                self._write(409, {"error": "stale run ID"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                result = json.loads(self.rfile.read(length))
                if not isinstance(result, dict):
                    raise ValueError("result must be an object")
                state.set_mobile_result(result)
            except (ValueError, json.JSONDecodeError) as exc:
                self._write(400, {"error": str(exc)})
                return
            self._write(200, {"accepted": True})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


async def wait_for_mobile_result(state: ProbeState, timeout: float = 45) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with state.condition:
            if state.mobile_result is not None:
                return state.mobile_result
        await asyncio.sleep(0.1)
    raise TimeoutError("native app did not submit a transport result")


def expected_guard(fault: str) -> str | None:
    return {
        "none": None,
        "withhold-audio": "received-audio",
        "withhold-event": "session-init-hud",
    }[fault]


async def run_probe(run_id: str, fault: str, control_path: Path, result_path: Path) -> None:
    server = ensure_livekit_server(require_docker=True)
    room_name = f"native-{run_id}"
    publisher_identity = f"python-{run_id}"
    mobile_identity = f"mobile-{run_id}"
    publisher_token = mint_access_token(
        api_key=server.api_key,
        api_secret=server.api_secret,
        room_name=room_name,
        identity=publisher_identity,
        participant_kind="agent",
    )
    mobile_token = mint_access_token(
        api_key=server.api_key,
        api_secret=server.api_secret,
        room_name=room_name,
        identity=mobile_identity,
    )
    state = ProbeState(
        {
            "run_id": run_id,
            "ws_url": server.ws_url,
            "token": mobile_token,
            "mobile_identity": mobile_identity,
            "publisher_identity": publisher_identity,
        }
    )
    fixture_server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, run_id))
    fixture_thread = threading.Thread(target=fixture_server.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_url = f"http://127.0.0.1:{fixture_server.server_port}/fixture"
    control_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "room_name": room_name,
                "fixture_url": fixture_url,
                "pid": os.getpid(),
                "status": "ready",
            }
        )
    )

    room: rtc.Room | None = None
    audio_source: rtc.AudioSource | None = None
    microphone_task: asyncio.Task[int] | None = None
    try:
        room = await connect_room(server.ws_url, publisher_token)
        await wait_for_peer(room, identity=mobile_identity, timeout=30)

        async def receive_microphone() -> int:
            track = await wait_for_audio_track(room, identity=mobile_identity, timeout=20)
            count = await count_audio_frames(track, timeout=15)
            state.set_microphone_frames(count)
            return count

        microphone_task = asyncio.create_task(receive_microphone())
        if fault != "withhold-audio":
            audio_source, _track, _publication = await publish_audio_frames(room, build_tone_frames())
        if fault != "withhold-event":
            await publish_game_event(room, E.SESSION_INIT, SESSION_INIT_FIXTURE)

        microphone_frames = await microphone_task
        mobile_result = await wait_for_mobile_result(state)
        guard = expected_guard(fault)
        if guard is None:
            assert_mobile_result(mobile_result, run_id, publisher_identity)
        elif mobile_result.get("guard_failed") != guard:
            raise ValueError(f"expected {guard} guard, got {mobile_result.get('guard_failed')!r}")
        result = safe_result(
            {
                **mobile_result,
                "room_name": room_name,
                "run_id": run_id,
                "publisher_identity": publisher_identity,
                "mobile_identity": mobile_identity,
                "microphone_frames": microphone_frames,
                "fault": fault,
                "expected_guard": guard,
            }
        )
        result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    finally:
        if microphone_task and not microphone_task.done():
            microphone_task.cancel()
            await asyncio.gather(microphone_task, return_exceptions=True)
        await aclose_audio(audio_source)
        if room is not None:
            await aclose_room(room)
        fixture_server.shutdown()
        fixture_server.server_close()
        fixture_thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fault", choices=("none", "withhold-audio", "withhold-event"), default="none")
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run_probe(args.run_id, args.fault, args.control, args.result))


if __name__ == "__main__":
    main()
