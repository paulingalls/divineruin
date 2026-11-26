"""Collect or prune the coverage map from the repository root."""

import argparse
import ast
import fcntl
import json
import os
import runpy
import signal
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proof_coverage_map import (
    MAP,
    OUTPUT_ENV,
    CoverageMap,
    load_map,
    ordinary_agent_source,
)


def current_inventory():
    generator = runpy.run_path("scripts/generate-proof-declarations.py")
    tasks = {
        generator["acceptance_name"](path, suffix)
        for path, parts in generator["acceptance_partitions"]().items()
        for suffix, _, _ in parts
    }
    sources = {path for path in generator["tracked"]("apps/agent", suffix=".py") if ordinary_agent_source(path)}
    if not tasks or not sources:
        raise ValueError("empty current acceptance task or ordinary source inventory")
    return tasks, sources


def function_regions(source):
    from coverage.regions import code_regions

    text = Path(source).read_text()
    for node in ast.walk(ast.parse(text, filename=source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == node.body[0].lineno:
            body = node.body[0]
            if (
                len(node.body) == 1
                and isinstance(body, ast.Expr)
                and isinstance(body.value, ast.Constant)
                and body.value.value is Ellipsis
            ):
                continue
            raise ValueError(f"{source}:{node.lineno}: coverage cannot distinguish an inline function body")
    return [(region.name, region.lines - {region.start}) for region in code_regions(text) if region.kind == "function"]


def reduce(directory, tasks, sources):
    from coverage import CoverageData

    receipts = {file.stem for file in directory.glob("*.json")}
    if receipts != tasks:
        raise ValueError(
            f"incomplete coverage receipts: missing={sorted(tasks - receipts)}, extra={sorted(receipts - tasks)}"
        )
    functions = defaultdict(lambda: defaultdict(set))
    regions = {}
    for task in sorted(tasks):
        receipt = json.loads((directory / (task + ".json")).read_text())
        root = Path(receipt["root"])
        if receipt["task"] != task or not root.is_absolute():
            raise ValueError(f"{task}: invalid coverage receipt")
        data_path = directory / (task + ".coverage")
        if not data_path.is_file() or not data_path.stat().st_size:
            raise ValueError(f"{task}: missing coverage data")
        data = CoverageData(basename=str(data_path))
        data.read()
        for filename in data.measured_files():
            path = Path(filename)
            if not path.is_relative_to(root):
                raise ValueError(f"{task}: coverage path outside task root: {filename}")
            source = path.relative_to(root).as_posix()
            if source not in sources:
                continue
            if source not in regions:
                regions[source] = function_regions(source)
            executed = set(data.lines(filename))
            for name, lines in regions[source]:
                if executed & lines:
                    functions[source][name].add(task)
    if not functions:
        raise ValueError("coverage run produced no executed ordinary agent functions")
    return CoverageMap(datetime.now(UTC), tasks, dict(functions))


def generate():
    with tempfile.TemporaryDirectory(prefix="proof-coverage-declarations-") as directory:
        subprocess.run(
            ["python3", "scripts/generate-proof-declarations.py"],
            env={**os.environ, "PROOF_DECLARATIONS": directory},
            check=True,
        )


def collect(directory, tasks, sources, super_run):
    started = time.monotonic()
    original = MAP.read_bytes()
    candidate = directory / MAP.name
    command = ["bunx", "proof", "run", "--fresh"]
    command += ["--set", "super"] if super_run else ["--tasks", *sorted(tasks)]
    try:
        old = load_map()
        CoverageMap(old.generated_at, set(), {}).write(MAP)
        subprocess.run(
            command,
            env={
                **os.environ,
                OUTPUT_ENV: str(directory),
                "ALLOW_PAID_TESTS": "",
                "REQUIRE_REAL_LLM": "",
                "REQUIRE_DOCKER": "1",
                "TESTCONTAINERS_RYUK_DISABLED": "true",
            },
            check=True,
        )
        coverage = reduce(directory, tasks, sources)
        coverage.write(candidate)
        print(
            f"Collected {len(tasks)} acceptance tasks in {time.monotonic() - started:.2f}s. Candidate map: {candidate}",
            flush=True,
        )
        coverage.write(MAP)
        generate()
    finally:
        MAP.write_bytes(original)
    if not super_run:
        coverage.write(MAP)


def interrupted(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["refresh", "prune", "due", "collect-super"])
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--map", type=Path, default=MAP)
    args = parser.parse_args()
    if args.action == "due":
        age = datetime.now(UTC) - load_map(args.map).generated_at
        print("due" if age >= timedelta(days=7) else "current")
        return
    signal.signal(signal.SIGTERM, interrupted)
    lock_path = subprocess.check_output(["git", "rev-parse", "--git-path", "proof-coverage.lock"], text=True).strip()
    with Path(lock_path).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        tasks, sources = current_inventory()
        if args.action == "prune":
            current = load_map()
            current.prune(tasks, sources).write(MAP)
        else:
            directory = args.directory.resolve() if args.directory else Path(tempfile.mkdtemp(prefix="proof-coverage-"))
            if args.directory:
                directory.mkdir()
            collect(directory, tasks, sources, args.action == "collect-super")


if __name__ == "__main__":
    main()
