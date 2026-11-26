"""Run one deterministic acceptance task, optionally recording its Python coverage."""

import json
import os
import subprocess
import sys
from pathlib import Path

OUTPUT_ENV = "PROOF_AGENT_COVERAGE_DIR"


def main():
    task, *arguments = sys.argv[1:]
    if not (directory := os.environ.get(OUTPUT_ENV)):
        os.execvp("pytest", ["pytest", *arguments])

    output = Path(directory)
    if not output.is_absolute() or not output.is_dir() or Path(task).name != task:
        raise ValueError(f"invalid coverage destination for {task}: {directory}")
    agent = Path.cwd().resolve()
    outcome = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--rcfile=/dev/null",
            f"--data-file={output / (task + '.coverage')}",
            f"--include={agent}/*",
            f"--omit={agent}/tests/*,{agent}/.venv/*",
            "-m",
            "pytest",
            *arguments,
        ],
        check=False,
    )
    if outcome.returncode == 0:
        with (output / (task + ".json")).open("x") as receipt:
            json.dump({"task": task, "root": str(agent.parents[1])}, receipt)
    return outcome.returncode


if __name__ == "__main__":
    sys.exit(main())
