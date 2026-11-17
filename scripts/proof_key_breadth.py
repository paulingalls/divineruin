"""Read expensive-task key breadth at clean HEAD without executing tasks."""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

FULL_KEY = (
    "**/uv.lock",
    "**/bun.lock",
    "**/pyproject.toml",
    "**/.python-version",
    "**/package.json",
    "**/tsconfig.json",
    "**/bunfig.toml",
    "docker-compose.yml",
    "scripts/proof-acceptance-stack.sh",
    "scripts/proof_acceptance_stack.py",
)


def command(root, *args, allowed=(0,)):
    result = subprocess.run(args, cwd=root, capture_output=True, check=False)
    if result.returncode not in allowed:
        raise ValueError(
            f"{' '.join(args)} exited {result.returncode}: "
            f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def clean_head(root):
    dirty = command(root, "git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none")
    flagged = [
        row[2:]
        for row in command(root, "git", "ls-files", "-v", "-z").split(b"\0")
        if row and (row[:1].islower() or row[:1] == b"S")
    ]
    if dirty or flagged:
        raise ValueError(f"requires clean HEAD; dirty or hidden paths: {dirty!r} {flagged!r}")
    return command(root, "git", "rev-parse", "HEAD").strip()


def task_roster(root):
    raw = command(root, "bunx", "proof", "status", "--ref", "HEAD", "--json", allowed=(0, 1))
    try:
        rows = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Proof status: invalid JSON: {error}") from error
    if not isinstance(rows, list) or not rows:
        raise ValueError("Proof status: expected nonempty task array")
    tasks = set()
    for row in rows:
        task = row.get("task") if isinstance(row, dict) else None
        if not isinstance(task, str) or not task.strip() or task in tasks:
            raise ValueError(f"Proof status: missing or duplicate task id: {task!r}")
        tasks.add(task)
    return tasks


def keyed_files(task, raw, eligible):
    headers = []
    paths = set()
    for line in raw.decode().splitlines():
        header = re.match(r"^(?:PROVEN|RUN|UNREACHED) (\S+): ", line)
        if header:
            headers.append(header[1])
        if line.startswith("undecidable:"):
            raise ValueError(f"{task}: {line}")
        if line.startswith("delivered keyed file"):
            record = line.removeprefix("delivered keyed file ").rsplit(" ", 2)
            if (
                not line.startswith("delivered keyed file ")
                or len(record) != 3
                or not record[0]
                or not re.fullmatch(r"[0-7]{6}", record[1])
                or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record[2])
            ):
                raise ValueError(f"{task}: malformed keyed file: {line}")
            paths.add(record[0])
        if line.startswith("delivered keyed member "):
            # Paths can contain spaces; compare against the tracked roster.
            member = line.removeprefix("delivered keyed member ")
            for path in eligible:
                if member.startswith(path + " "):
                    raise ValueError(f"{task}: partial member key on eligible file {path}")
    if headers != [task] or not paths:
        raise ValueError(f"{task}: empty, missing, duplicate or unparseable why output (headers={headers!r})")
    return paths


def measure(limits):
    root = Path(command(Path.cwd(), "git", "rev-parse", "--show-toplevel").decode().strip())
    head = clean_head(root)
    tracked = command(root, "git", "ls-files", "-z").decode().split("\0")
    counts = {path: 0 for path in tracked if path and not any(PurePosixPath(path).full_match(p) for p in FULL_KEY)}
    if not counts:
        raise ValueError("no eligible tracked files")
    matches = []
    for pattern, threshold in limits:
        selected = [path for path in counts if PurePosixPath(path).full_match(pattern)]
        if not selected:
            raise ValueError(f"--limit {pattern!r}: no eligible files match")
        matches.append((selected, threshold))
    tasks = task_roster(root)
    completed = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(command, root, "bunx", "proof", "why", task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                paths = keyed_files(task, future.result(), counts)
            except (ValueError, UnicodeError, OSError) as error:
                raise ValueError(f"{task}: {error}") from error
            if task in completed:
                raise ValueError(f"{task}: duplicate task output")
            completed.add(task)
            if clean_head(root) != head:
                raise ValueError("HEAD changed during measurement")
            if task.startswith(("agent-acceptance:", "e2e:")):
                for path in paths & counts.keys():
                    counts[path] += 1
    if completed != tasks:
        raise ValueError(f"missing task outputs: {sorted(tasks - completed)}")
    if clean_head(root) != head:
        raise ValueError("HEAD changed during measurement")
    violations = sorted(
        {(path, counts[path], limit) for paths, limit in matches for path in paths if counts[path] > limit}
    )
    lines = [
        f"distance={sum(n > 20 for n in counts.values())} mean={sum(counts.values()) / len(counts):.1f} files={len(counts)}"
    ]
    lines.extend(f"{path}={count}" for path, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10])
    return lines, violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", nargs=2, action="append", default=[], metavar=("GLOB", "N"))
    args = parser.parse_args()
    limits = []
    for pattern, threshold in args.limit:
        try:
            limits.append((pattern, int(threshold)))
        except ValueError:
            parser.error(f"--limit {pattern!r}: N must be an integer")
    try:
        lines, violations = measure(limits)
    except (OSError, ValueError) as error:
        print(f"proof key breadth: {error}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    for path, count, limit in violations:
        print(f"--limit {path}: count={count} exceeds {limit}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
