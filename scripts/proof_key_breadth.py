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


def keyed_files(task, row, eligible):
    for field in ("files", "members", "reasons"):
        if not isinstance(row.get(field), list):
            raise ValueError(f"{task}: expected {field} array")
    if row["reasons"]:
        raise ValueError(f"{task}: undecidable: {row['reasons']!r}")

    paths = set()
    for record in row["files"]:
        if (
            not isinstance(record, list)
            or len(record) != 3
            or not all(isinstance(part, str) for part in record)
            or not record[0]
            or not re.fullmatch(r"[0-7]{6}", record[1])
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record[2])
        ):
            raise ValueError(f"{task}: malformed keyed file: {record!r}")
        paths.add(record[0])
    if not paths:
        raise ValueError(f"{task}: no keyed files")

    for record in row["members"]:
        if (
            not isinstance(record, list)
            or len(record) != 4
            or not all(isinstance(part, str) for part in record)
            or not record[0]
        ):
            raise ValueError(f"{task}: malformed keyed member: {record!r}")
        if record[0] in eligible:
            raise ValueError(f"{task}: partial member key on eligible file {record[0]}")
    return paths


def key_rows(raw):
    try:
        rows = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"Proof key parts: invalid JSON: {error}") from error
    if not isinstance(rows, list):
        raise ValueError("Proof key parts: expected a task array")
    for row in rows:
        task = row.get("task") if isinstance(row, dict) else None
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"Proof key parts: invalid task id: {task!r}")
        yield task, row


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
    ordered_tasks = sorted(tasks)
    workers = min(16, len(tasks))
    shards = [ordered_tasks[index::workers] for index in range(workers)]
    completed = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(command, root, "bun", "scripts/proof_key_breadth_parts.ts", *shard) for shard in shards]
        for future in as_completed(futures):
            raw = future.result()
            if clean_head(root) != head:
                raise ValueError("HEAD changed during measurement")
            for task, row in key_rows(raw):
                if task in completed:
                    raise ValueError(f"{task}: duplicate task output")
                completed.add(task)
                paths = keyed_files(task, row, counts)
                if task.startswith(("agent-acceptance:", "e2e:")):
                    for path in paths & counts.keys():
                        counts[path] += 1
    if completed != tasks:
        raise ValueError(
            f"missing task outputs: {sorted(tasks - completed)}; extra task outputs: {sorted(completed - tasks)}"
        )
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
