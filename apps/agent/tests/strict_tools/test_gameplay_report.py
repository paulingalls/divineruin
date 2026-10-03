"""Independent matrix processes must retain their own complete evidence."""

import json
import os
import subprocess
import sys
from pathlib import Path

_WORKER = """
import json
import sys
from pathlib import Path
from acceptance import strict_luna_runtime as runtime
from acceptance import test_strict_luna_gameplay as matrix

# Confine even a regression to the shared filename to this test's sandbox.
runtime.REPORT_PATH = Path(sys.argv[1]) / runtime.REPORT_PATH.name
matrix.REPORT_PATH = runtime.REPORT_PATH
matrix._fresh_report.__wrapped__()
runtime.append_report({"id": sys.argv[2]})
print(runtime.REPORT_PATH, flush=True)
sys.stdin.readline()
print(runtime.REPORT_PATH.read_text(), flush=True)
"""


def test_matrix_processes_preserve_separate_reports(tmp_path: Path) -> None:
    agent_root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(agent_root), str(agent_root / "tests")))}
    workers: list[subprocess.Popen[str]] = []
    try:
        paths = []
        for case_id in ("first", "second"):
            worker = subprocess.Popen(
                [sys.executable, "-c", _WORKER, str(tmp_path), case_id],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            workers.append(worker)
            assert worker.stdout is not None
            paths.append(Path(worker.stdout.readline().strip()))
        for worker, case_id in zip(workers, ("first", "second"), strict=True):
            output, errors = worker.communicate("read\n", timeout=60)
            assert worker.returncode == 0, errors
            assert [json.loads(line) for line in output.splitlines() if line] == [{"id": case_id}]
        assert paths[0] != paths[1]
        assert [json.loads(path.read_text()) for path in paths] == [{"id": "first"}, {"id": "second"}]
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
            worker.communicate()
