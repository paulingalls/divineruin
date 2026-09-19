import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("kind", [signal.SIGINT, signal.SIGTERM])
def test_signal_cancels_task_and_awaits_finally(tmp_path: Path, kind: signal.Signals) -> None:
    ready = tmp_path / "ready"
    closed = tmp_path / "closed"
    source = f"""
import asyncio
from pathlib import Path
from native_transport.lifecycle import run_cancellable
async def run():
    try:
        Path({str(ready)!r}).write_text('ready')
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(.05)
        Path({str(closed)!r}).write_text('closed')
asyncio.run(run_cancellable(run))
"""
    child = subprocess.Popen(
        [sys.executable, "-c", source],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert child.poll() is None
            time.sleep(0.01)
        assert ready.exists()
        child.send_signal(kind)
        _, stderr = child.communicate(timeout=5)
        # Exit 1 with no KeyboardInterrupt is the handler's signature: the default
        # SIGTERM kills the process outright, and the default SIGINT also cancels the
        # task through asyncio.run's shutdown, so "CancelledError and nonzero" alone
        # passes with no handler installed at all.
        assert child.returncode == 1
        assert b"KeyboardInterrupt" not in stderr
        assert b"CancelledError" in stderr
        assert closed.read_text() == "closed"
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
