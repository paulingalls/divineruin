"""Measure task-key changes for independent newline edits without running tests."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE_PATHS = (
    "docs/INDEX.md",
    "content/npcs.json",
    "scripts/seed_content.py",
    "apps/agent/dice.py",
    "packages/shared/src/index.ts",
)


def command(args, *, cwd, env, data=None, allowed=(0,)):
    result = subprocess.run(args, cwd=cwd, env=env, input=data, capture_output=True, check=False)
    if result.returncode not in allowed:
        raise ValueError(
            f"{' '.join(args)} exited {result.returncode}:\n"
            f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}"
        )
    return result


def task_keys(ref, root, env):
    result = command(["bunx", "proof", "status", "--ref", ref, "--json"], cwd=root, env=env, allowed=(0, 1))
    diagnostics = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
    try:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not rows:
            raise ValueError("expected a nonempty task array")
        keys = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"invalid task row: {row!r}")
            task, key = row.get("task"), row.get("key")
            if not isinstance(task, str) or not task or task in keys:
                raise ValueError(f"missing or duplicate task id: {task!r}")
            if not isinstance(key, str) or not key:
                raise ValueError(f"task {task}: missing or undecidable key")
            keys[task] = key
        return keys
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Proof status at {ref}: {error}\n{diagnostics}") from error


def measure():
    env = os.environ.copy()
    root = command(["git", "rev-parse", "--show-toplevel"], cwd=Path.cwd(), env=env).stdout.decode().strip()

    def git(*args, data=None):
        return command(["git", *args], cwd=root, env=env, data=data).stdout

    head = git("rev-parse", "HEAD").decode().strip()
    objects = git("rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    with tempfile.TemporaryDirectory(prefix="proof-selection-probe-") as temporary:
        private_objects = Path(temporary) / "objects"
        private_objects.mkdir()
        env.update(
            GIT_OBJECT_DIRECTORY=str(private_objects),
            GIT_ALTERNATE_OBJECT_DIRECTORIES=objects,
            GIT_INDEX_FILE=str(Path(temporary) / "index"),
            GIT_AUTHOR_NAME="Proof selection probe",
            GIT_AUTHOR_EMAIL="probe@invalid",
            GIT_COMMITTER_NAME="Proof selection probe",
            GIT_COMMITTER_EMAIL="probe@invalid",
        )
        sources = {}
        for path in PROBE_PATHS:
            entry = git("ls-tree", "-z", head, "--", path).split(b"\0")[0]
            if not entry:
                raise ValueError(f"{path}: missing committed probe path at {head}")
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            if name.decode() != path or kind != "blob" or mode not in ("100644", "100755"):
                raise ValueError(f"{path}: probe path must be a committed regular-file blob")
            sources[path] = (mode, git("cat-file", "blob", oid))

        baseline = task_keys(head, root, env)
        counts = {}
        for path, (mode, original) in sources.items():
            git("read-tree", head)
            blob = git("hash-object", "-w", "--stdin", data=original + b"\n").decode().strip()
            git("update-index", "--cacheinfo", mode, blob, path)
            tree = git("write-tree").decode().strip()
            edited = git("commit-tree", tree, "-p", head, data=b"Probe newline edit\n").decode().strip()
            keys = task_keys(edited, root, env)
            if keys.keys() != baseline.keys():
                raise ValueError(
                    f"Proof status at {edited} ({path}): task roster differs; "
                    f"missing={sorted(baseline.keys() - keys.keys())}, "
                    f"added={sorted(keys.keys() - baseline.keys())}"
                )
            counts[path] = sum(key != baseline[task] for task, key in keys.items())
    return f"distance={sum(counts.values())} " + " ".join(f"{path}={count}" for path, count in counts.items())


if __name__ == "__main__":
    try:
        print(measure())
    except (OSError, ValueError) as error:
        print(f"proof selection probe: {error}", file=sys.stderr)
        sys.exit(1)
