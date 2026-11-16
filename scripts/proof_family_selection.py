"""Resolve runtime Python roots and assign family-owned acceptance keys."""

import ast
import json
import re
from pathlib import Path

ROOTS = ("apps/agent", "apps/agent/tests", "scripts")
SYNTHETIC = (
    "creation_tools",
    "db_mutations_companion",
    "companion_relationship_queries",
    "combat_agent",
)
PATH_LOADED = {
    "apps/agent/tests/acceptance/test_m22_audio_completeness_capstone.py": ["scripts/audio/generate_spell_sfx.py"],
}
# These imports assert ModuleNotFoundError; there is no runtime module to include.
ABSENT_IMPORTS = {"apps/agent/tests/acceptance/test_exploration_collapse.py"}


def load_families():
    path = "scripts/proof-families.json"
    rows = json.loads(Path(path).read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected nonempty family list")
    families = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "tests", "owns"}:
            raise ValueError(f"{path}: invalid family schema: {row!r}")
        name = row["name"]
        if not isinstance(name, str) or not name.strip() or name in families:
            raise ValueError(f"{path}: empty or duplicate family name: {name!r}")
        patterns = {}
        for field in ("tests", "owns"):
            values = row[field]
            if not isinstance(values, list) or (field == "tests" and not values):
                raise ValueError(f"family {name}: {field} must be a {'nonempty ' if field == 'tests' else ''}list")
            try:
                if any(not isinstance(v, str) or not v for v in values):
                    raise ValueError(f"family {name}: invalid {field} pattern")
                patterns[field] = [re.compile(v) for v in values]
            except re.error as error:
                raise ValueError(f"family {name}: invalid {field} regex: {error}") from error
        families[name] = patterns
    return families


def matches(patterns, path):
    return any(pattern.fullmatch(path) for pattern in patterns)


def runtime_closure(entry, graph):
    pending = [entry]
    closure = set()
    while pending:
        path = pending.pop()
        if path in closure:
            continue
        if path not in graph:
            raise ValueError(f"{entry}: missing Python root {path}")
        closure.add(path)
        pending.extend(set(graph[path]["closure"]) - closure)
        text = Path(path).read_text()
        if graph[path].get("localReason") and path not in ABSENT_IMPORTS:
            if path == "apps/agent/tests/agent_tool_profiles.py":
                roots = {str(p) for p in Path("apps/agent").glob("*_agent.py")}
            else:
                literals = {
                    node.value
                    for node in ast.walk(ast.parse(text))
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", node.value)
                }
                roots = {
                    str(Path(root) / (literal.replace(".", "/") + ".py")) for root in ROOTS for literal in literals
                } & graph.keys()
            if not roots:
                raise ValueError(f"{path}: unrooted dynamic import: {graph[path]['localReason']}")
            pending.extend(roots - closure)
        if "spec_from_file_location" in text or "run_path" in text:
            if path not in PATH_LOADED:
                raise ValueError(f"{path}: undeclared path-loaded Python root")
            pending.extend(set(PATH_LOADED[path]) - closure)
    return closure


def task_inventory(acceptance, e2e, graph, families):
    inventory = {}
    cache = {}

    def closure(path):
        if path not in cache:
            cache[path] = runtime_closure(path, graph)
        return cache[path]

    for task, paths in {**{t: [p] for t, p in acceptance.items()}, **e2e}.items():
        memberships = set()
        for path in paths:
            owners = [name for name, family in families.items() if matches(family["tests"], path)]
            if len(owners) != 1:
                raise ValueError(f"task {task}, path {path}: expected one family; matching families={owners}")
            memberships.update(owners)
        if len(memberships) != 1:
            raise ValueError(f"task {task}: empty or conflicting families {sorted(memberships)}")
        entry = acceptance.get(task)
        if entry:
            preferred = set(closure(entry))
            roots = [
                "apps/agent/tests/conftest.py",
                *[f"apps/agent/{m}.py" for m in SYNTHETIC],
            ]
            roots += [str(p / "conftest.py") for p in Path(entry).parents if (p / "conftest.py").is_file()]
            full = preferred | set().union(*(closure(p) for p in roots))
        elif task == "e2e:chromium":
            entry = "e2e/fixtures/inventory-snapshot.py"
            preferred = full = set(closure(entry))
        else:
            entry = paths[0]
            preferred = full = set()
        inventory[task] = {
            "path": entry,
            "family": memberships.pop(),
            "preferred": preferred,
            "closure": full,
        }
    if not inventory or not acceptance or any(not inventory[t]["closure"] for t in acceptance):
        raise ValueError("empty acceptance task/closure inventory")
    for name in families:
        if not any(m["family"] == name for m in inventory.values()):
            raise ValueError(f"empty family {name}: no tasks")
    return inventory


def select_sources(inventory, families, sources, infrastructure):
    assignments = {task: set() for task in inventory}
    representatives = {}
    for source in sorted(sources):
        readers = {task for task, meta in inventory.items() if source in meta["closure"]}
        owners = {name for name, family in families.items() if matches(family["owns"], source)}
        selected = {task for task, meta in inventory.items() if meta["family"] in owners or meta["path"] == source}
        shared = sum(task.startswith("agent-acceptance:") for task in readers) > 10
        by_family = {}
        if not shared:
            selected.update(readers)
        else:
            for family in families:
                reaching = {task for task in readers if inventory[task]["family"] == family}
                preferred = {task for task in reaching if source in inventory[task]["preferred"]}
                candidates = sorted(
                    preferred or reaching,
                    key=lambda task: (
                        len(inventory[task]["closure"]),
                        inventory[task]["path"],
                        task,
                    ),
                )
                by_family[family] = set(candidates[:2])
                selected.update(by_family[family])
        if source in infrastructure:
            selected.update(inventory)
        for task in selected:
            assignments[task].add(source)
        representatives[source] = by_family
    return assignments, representatives


def audit_selection(tasks, inventory, families, sources, infrastructure, representatives):
    for source in sorted(sources):
        readers = {task for task, meta in inventory.items() if source in meta["closure"]}
        shared = sum(task.startswith("agent-acceptance:") for task in readers) > 10
        owners = {name for name, family in families.items() if matches(family["owns"], source)}
        receiving = {t for t in inventory if source in tasks[t]["keyed"] and source in tasks[t]["inputs"]}
        for task, meta in inventory.items():
            family = meta["family"]
            required = family in owners or meta["path"] == source or source in infrastructure
            if required or (task in readers and not shared):
                if task not in receiving:
                    raise ValueError(f"orphan {source}: task {task}, family {family}: missing direct coverage/input")
            elif task in readers:
                reps = representatives[source][family]
                if not reps or not reps <= receiving:
                    raise ValueError(
                        f"orphan {source}: task {task}, family {family}: missing representative coverage/input"
                    )
        for family, reps in representatives[source].items():
            reaching = {t for t in readers if inventory[t]["family"] == family}
            preferred = {t for t in reaching if source in inventory[t]["preferred"]}
            if len(reps) > 2 or not reps <= (preferred or reaching):
                raise ValueError(f"{source}: family {family}: invalid representatives {sorted(reps)}")
            selected = {t for t in receiving if inventory[t]["family"] == family}
            if family not in owners and source not in infrastructure:
                selected -= {t for t in selected if inventory[t]["path"] == source}
                if len(selected) > 2:
                    raise ValueError(f"{source}: family {family}: representative cap exceeded {sorted(selected)}")
