"""Read and apply the weekly agent acceptance coverage map."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAP = Path("scripts/proof-coverage-map.json")
COLLECTOR = "scripts/proof_coverage_collect.py"
OUTPUT_ENV = "PROOF_AGENT_COVERAGE_DIR"
TASK_PREFIX = "agent-acceptance:"
# The measured maximum, 5, preserves full coverage. Only combat_martial.py and
# db_mutations.py need a fifth combat representative, adding a few seconds when they change.
COVER_BUDGET = 5


def ordinary_agent_source(source):
    path = Path(source)
    return (
        path.as_posix() == source
        and path.parts[:2] == ("apps", "agent")
        and ".." not in path.parts
        and not any(part.startswith(".") for part in path.parts)
        and path.parts[2:3] != ("tests",)
        and path.suffix == ".py"
    )


def task_order(inventory, task):
    return len(inventory[task]["closure"]), inventory[task]["path"], task


def first_reader(inventory, candidates):
    return min(candidates, key=lambda task: task_order(inventory, task))


def ordinary_candidates(inventory, source, reaching):
    direct = {task for task in reaching if source in inventory[task]["direct"]}
    preferred = {task for task in reaching if source in inventory[task]["preferred"]}
    return direct or preferred or reaching


def covers(functions, tasks):
    return {function for function, readers in functions.items() if readers & tasks}


@dataclass
class CoverageMap:
    generated_at: datetime
    tasks: set[str]
    sources: dict[str, dict[str, set[str]]]

    def prune(self, tasks, sources):
        kept = self.tasks & tasks
        return CoverageMap(
            self.generated_at,
            kept,
            {
                source: {name: readers & kept for name, readers in functions.items() if readers & kept}
                for source, functions in self.sources.items()
                if kept and source in sources
            },
        )

    def write(self, path):
        data = {
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "tasks": sorted(self.tasks),
            **{
                source: {name: sorted(tasks) for name, tasks in sorted(functions.items())}
                for source, functions in sorted(self.sources.items())
            },
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.replace(path)

    def validate(self, tasks, sources):
        stale_tasks = self.tasks - tasks
        stale_sources = self.sources.keys() - sources
        if stale_tasks or stale_sources:
            raise ValueError(
                f"{MAP}: stale tasks={sorted(stale_tasks)}, stale sources={sorted(stale_sources)}. "
                "Run python3 scripts/proof_coverage_refresh.py prune."
            )

    def select(self, source, inventory, reaching, required):
        functions, mapped, fallback = self.family(source, inventory, reaching, required)
        return greedy_cover(inventory, functions, mapped, required) | ({fallback} if fallback else set())

    def audit(self, source, family, inventory, reaching, selected, required):
        functions, _, fallback = self.family(source, inventory, reaching, required)
        audit_cover(source, family, functions, selected, required, fallback)

    def family(self, source, inventory, reaching, required):
        fallback_candidates = ordinary_candidates(inventory, source, reaching)
        acceptance = {task for task in reaching if task.startswith(TASK_PREFIX)}
        if not acceptance or source not in self.sources:
            return (
                {},
                set(),
                first_reader(inventory, fallback_candidates) if not required else None,
            )

        mapped = acceptance & self.tasks
        missing = acceptance - self.tasks
        functions = {name: readers & mapped for name, readers in self.sources[source].items() if readers & mapped}
        fallback = first_reader(inventory, missing) if missing else None
        if not functions and not required and fallback is None:
            fallback = first_reader(inventory, fallback_candidates)
        return functions, mapped, fallback


def load_map(path=MAP):
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not {"generated_at", "tasks"} <= payload.keys():
        raise ValueError(f"{path}: expected generated_at, tasks and agent source entries")
    generated_at = datetime.fromisoformat(payload["generated_at"])
    if generated_at.utcoffset() is None:
        raise ValueError(f"{path}: generated_at requires a UTC offset")
    tasks = string_set(payload["tasks"], f"{path}: tasks")
    if any(not task.startswith(TASK_PREFIX) for task in tasks):
        raise ValueError(f"{path}: invalid acceptance task roster")
    sources = payload.keys() - {"generated_at", "tasks"}
    if not tasks and sources:
        raise ValueError(f"{path}: sources require a task roster")
    result = {}
    for source in sorted(sources):
        functions = payload[source]
        if not ordinary_agent_source(source) or not isinstance(functions, dict):
            raise ValueError(f"{path}: invalid source entry {source}")
        result[source] = {}
        for name, readers in functions.items():
            measured = string_set(readers, f"{path}: {source}: {name}")
            if not name or not measured or not measured <= tasks:
                raise ValueError(f"{path}: {source}: {name}: invalid readers {sorted(measured - tasks)}")
            result[source][name] = measured
    return CoverageMap(generated_at, tasks, result)


def string_set(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label}: expected a list of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label}: duplicate entries")
    return set(value)


def greedy_cover(inventory, functions, candidates, required):
    missing = functions.keys() - covers(functions, required)
    gains = {task: {name for name in missing if task in functions[name]} for task in candidates - required}
    selected = set()
    while missing:
        task = min(gains, key=lambda t: (-len(gains[t] & missing), *task_order(inventory, t)))
        selected.add(task)
        missing -= gains.pop(task)
    return selected


def audit_cover(source, family, functions, selected, required, fallback):
    if fallback is not None and fallback not in selected:
        raise ValueError(f"{source}: family {family}: missing fallback representative {fallback}")
    missing = functions.keys() - covers(functions, selected)
    additions = selected - required - {fallback}
    if missing or len(additions) > COVER_BUDGET:
        raise ValueError(
            f"{source}: family {family}: coverage cap {COVER_BUDGET}, needs {len(additions)}, "
            f"uncovered functions {sorted(missing)}"
        )
