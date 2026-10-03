"""Interrupt the actual owned probe and silent process family while a microphone command is pending."""

import asyncio
import json
import os
import signal
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from acceptance._livekit_client import (
    aclose_audio,
    aclose_room,
    connect_room,
    create_microphone_track,
)
from livekit import rtc

import db


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def assert_active_family(owned):
    assert set(owned) == {"probe", "stimulus", "descendant"}, "incomplete owned process family"
    assert all(alive(pid) for pid in owned.values()), "cleanup fixture was not active"


async def read_json(path):
    async with asyncio.timeout(40):
        while not path.exists():
            await asyncio.sleep(0.02)
        return json.loads(path.read_text())


def stimulus_command(scratch):
    code = """
import json, signal, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
def stop(*_):
    child.terminate()
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
Path(sys.argv[1]).write_text(json.dumps({"pid": child.pid}))
while True:
    time.sleep(1)
"""
    return ["python3", "-c", code, str(scratch / "silent-child.json")]


async def interrupt_probe(signal_name, scratch):
    root = Path(__file__).resolve().parents[4]
    run_id = f"cleanup-{uuid.uuid4().hex[:10]}"
    control = scratch / "control.json"
    result = scratch / "result.json"
    children = scratch / "children.json"
    runner = scratch / "runner.ts"
    runner.write_text(
        "import { withOwnedProcesses } from "
        + json.dumps(str(root / "apps/mobile/scripts/native-transport-processes.ts"))
        + ";\n"
        + "await withOwnedProcesses(async scope => {\n"
        + "const probe = scope.spawn("
        + json.dumps(
            [
                "uv",
                "run",
                "--project",
                str(root / "apps/agent"),
                "python",
                str(root / "apps/agent/choir_capstone_probe.py"),
                "--run-id",
                run_id,
                "--choir-fault",
                "none",
                "--control",
                str(control),
                "--result",
                str(result),
            ]
        )
        + ", {cwd:"
        + json.dumps(str(root))
        + ",env:process.env});\n"
        + "while (!await Bun.file("
        + json.dumps(str(control))
        + ").exists()) await scope.wait(Bun.sleep(20));\n"
        + "const stimulus = scope.spawn("
        + json.dumps(stimulus_command(scratch))
        + ", {cwd:"
        + json.dumps(str(root))
        + "});\n"
        + "await Bun.write("
        + json.dumps(str(children))
        + ",JSON.stringify({probe:probe.pid,stimulus:stimulus.pid}));\n"
        + "await scope.wait(new Promise(() => {}));\n});\n"
    )
    log = (scratch / "process.log").open("wb")
    child = await asyncio.create_subprocess_exec("bun", str(runner), cwd=root, stdout=log, stderr=log)
    mobile = audio = None
    pump = None
    owned = {}
    try:
        fixture_control = await read_json(control)
        with urllib.request.urlopen(fixture_control["fixture_url"] + "?run_id=" + run_id, timeout=2) as response:
            fixture = json.load(response)
        mobile = await connect_room(fixture["ws_url"], fixture["token"])
        audio, _, _ = await create_microphone_track(mobile, sample_rate=48000, channels=1, name="cleanup-microphone")

        async def silence():
            while True:
                await audio.capture_frame(rtc.AudioFrame(b"\0" * 960, 48000, 1, 480))
                await asyncio.sleep(0.01)

        pump = asyncio.create_task(silence())
        async with asyncio.timeout(40):
            while True:
                with urllib.request.urlopen(
                    fixture_control["fixture_url"].replace("/fixture", "/status") + "?run_id=" + run_id, timeout=2
                ) as response:
                    status = json.load(response)
                assert status["run_id"] == run_id
                if status.get("requested_turn") == 1 and status["microphone_frames"] >= 5:
                    break
                assert child.returncode is None, "cleanup probe exited before pending command"
                await asyncio.sleep(0.02)
        owned = await read_json(children)
        playback = await read_json(scratch / "silent-child.json")
        owned["descendant"] = playback["pid"]
        assert_active_family(owned)
        child.send_signal(getattr(signal, signal_name))
        async with asyncio.timeout(15):
            assert await child.wait() != 0, "interrupted scope certified success"
        assert not result.exists(), "interrupted probe wrote a successful result"
        assert not any(alive(pid) for pid in owned.values()), "owned native child survived interruption"
        assert await read_json(scratch / "cleanup.json") == {"player_removed": True, "combat_removed": True}
        assert (
            await (await db.get_pool()).fetchval(
                "SELECT count(*) FROM players WHERE player_id=$1", fixture["mobile_identity"]
            )
            == 0
        )
        try:
            with urllib.request.urlopen(fixture_control["fixture_url"] + "?run_id=" + run_id, timeout=1):
                raise AssertionError("owned control endpoint survived interruption")
        except urllib.error.URLError:
            pass
        assert mobile.isconnected(), "cleanup stopped reused LiveKit infrastructure"
    finally:
        if child.returncode is None:
            child.send_signal(signal.SIGTERM)
            await child.wait()
        for pid in owned.values():
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        await aclose_audio(audio)
        if mobile is not None:
            await aclose_room(mobile)
        log.close()
