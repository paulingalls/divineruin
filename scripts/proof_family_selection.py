"""Resolve runtime Python roots and assign family-owned acceptance keys."""

import ast
import json
import re
from pathlib import Path

SHARED_CONTENT = {"content/players.json"}
SHARED_INPUTS = {"scripts/seed_content.py", "scripts/migrations/**", *SHARED_CONTENT}
SEED_REPRESENTATIVES = {
    "agent-acceptance:test_greyvale_arc_walk",
    "agent-acceptance:test_seed_content_cache",
}

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


def load_families(content):
    path = "scripts/proof-families.json"
    rows = json.loads(Path(path).read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected nonempty family list")
    families = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "tests", "owns", "reads"}:
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
        reads = row["reads"]
        if not isinstance(reads, list) or any(not isinstance(v, str) or v not in content for v in reads):
            raise ValueError(f"family {name}: reads must name existing content JSON paths: {reads!r}")
        if len(set(reads)) != len(reads) or SHARED_CONTENT.intersection(reads):
            raise ValueError(f"family {name}: duplicate or shared reads: {reads!r}")
        families[name] = {**patterns, "reads": set(reads)}
    owned = set().union(*(family["reads"] for family in families.values()), SHARED_CONTENT)
    if missing := content - owned:
        raise ValueError(f"content has no reader family: {sorted(missing)}")
    return families


def matches(patterns, path):
    return any(pattern.fullmatch(path) for pattern in patterns)


def explicit_roots(path, graph):
    local = set()
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
        local.update(roots)
    if "spec_from_file_location" in text or "run_path" in text:
        if path not in PATH_LOADED:
            raise ValueError(f"{path}: undeclared path-loaded Python root")
        local.update(PATH_LOADED[path])
    return local


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
        pending.extend(explicit_roots(path, graph) - closure)
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
            "direct": (set(graph[entry]["direct"]) - {entry}) | explicit_roots(entry, graph)
            if entry in graph
            else set(),
            "closure": full,
        }
    if not inventory or not acceptance or any(not inventory[t]["closure"] for t in acceptance):
        raise ValueError("empty acceptance task/closure inventory")
    for name in families:
        if not any(m["family"] == name for m in inventory.values()):
            raise ValueError(f"empty family {name}: no tasks")
    return inventory


NON_PYTHON = {"scripts/worktree-common.sh", "scripts/ensure-db.ts"}


def harness_source(source):
    return source.startswith("apps/agent/tests/") or source in NON_PYTHON


def select_readers(inventory, source, readers, budget):
    if sum(task.startswith("agent-acceptance:") for task in readers) <= 10:
        return set(readers)
    selected = set()
    for family in {inventory[t]["family"] for t in readers}:
        reaching = {t for t in readers if inventory[t]["family"] == family}
        preferred = {t for t in reaching if source in inventory[t]["preferred"]}
        candidates = sorted(
            preferred or reaching,
            key=lambda t: (len(inventory[t]["closure"]), inventory[t]["path"], t),
        )
        selected.update(candidates[:budget])
    return selected


def source_readers(inventory, families, source):
    readers = {t for t, m in inventory.items() if source in m["closure"]}
    owners = {name for name, family in families.items() if matches(family["owns"], source)}
    own = {t for t, m in inventory.items() if m["path"] == source}
    return readers, owners, own


def ordinary_candidates(inventory, source, reaching):
    direct = {t for t in reaching if source in inventory[t]["direct"]}
    preferred = {t for t in reaching if source in inventory[t]["preferred"]}
    return direct or preferred or reaching


def first_reader(inventory, candidates):
    return min(
        candidates,
        key=lambda t: (len(inventory[t]["closure"]), inventory[t]["path"], t),
    )


def select_sources(inventory, families, sources):
    assignments = {task: set() for task in inventory}
    for source in sorted(sources):
        readers, owners, selected = source_readers(inventory, families, source)
        if harness_source(source):
            selected |= select_readers(inventory, source, readers, 1)
            selected.update(t for t, m in inventory.items() if m["family"] in owners)
        else:
            direct = {t for t, m in inventory.items() if source in m["direct"]}
            if sum(t.startswith("agent-acceptance:") for t in direct) <= 10:
                selected |= direct
            shared = sum(t.startswith("agent-acceptance:") for t in readers) > 10
            for family in owners | {inventory[t]["family"] for t in readers}:
                members = {t for t, m in inventory.items() if m["family"] == family}
                reaching = readers & members
                if family not in owners and not shared:
                    selected |= reaching
                elif not selected & members:
                    candidates = ordinary_candidates(inventory, source, reaching) or members
                    selected.add(first_reader(inventory, candidates))
        for task in selected:
            assignments[task].add(source)
    return assignments


def audit_readers(source, inventory, readers, receiving, required, budget):
    shared = sum(t.startswith("agent-acceptance:") for t in readers) > 10
    expected = required | (set() if shared else readers)
    if missing := expected - receiving:
        raise ValueError(f"orphan {source}: missing direct coverage/input: {sorted(missing)}")
    if extra := receiving - readers - required:
        raise ValueError(f"{source}: unexpected receivers: {sorted(extra)}")
    if shared:
        for family in {inventory[t]["family"] for t in readers}:
            reaching = {t for t in readers if inventory[t]["family"] == family}
            selected = {t for t in receiving - required if inventory[t]["family"] == family}
            if not receiving & reaching:
                raise ValueError(f"orphan {source}: family {family}: missing representative coverage/input")
            if len(selected) > budget:
                raise ValueError(f"{source}: family {family}: representative cap exceeded {sorted(selected)}")


def audit_selection(tasks, inventory, families, sources):
    for source in sorted(sources):
        readers, owners, own = source_readers(inventory, families, source)
        receiving = {t for t in inventory if source in tasks[t]["keyed"] and source in tasks[t]["inputs"]}
        if harness_source(source):
            required = own | {t for t, m in inventory.items() if m["family"] in owners}
            audit_readers(source, inventory, readers, receiving, required, 1)
            continue
        direct = {t for t, m in inventory.items() if source in m["direct"]}
        required = own | (direct if sum(t.startswith("agent-acceptance:") for t in direct) <= 10 else set())
        if missing := required - receiving:
            raise ValueError(f"orphan {source}: missing direct coverage/input: {sorted(missing)}")
        shared = sum(t.startswith("agent-acceptance:") for t in readers) > 10
        for family in families:
            members = {t for t, m in inventory.items() if m["family"] == family}
            reaching = readers & members
            selected = receiving & members
            if family not in owners and not shared:
                if selected != (reaching | (required & members)):
                    raise ValueError(f"{source}: family {family}: reader coverage/input mismatch")
                continue
            if family not in owners and not reaching:
                if selected:
                    raise ValueError(f"{source}: family {family}: unexpected receivers {sorted(selected)}")
                continue
            if not selected:
                raise ValueError(f"orphan {source}: family {family}: missing representative coverage/input")
            if len(selected - required) > (0 if required & members else 1):
                raise ValueError(f"{source}: family {family}: representative cap exceeded {sorted(selected)}")
            candidates = ordinary_candidates(inventory, source, reaching) or members
            if not selected - required <= candidates:
                raise ValueError(f"{source}: family {family}: invalid representatives {sorted(selected)}")


def content_inventory():
    paths = {str(path) for path in Path("content").glob("*.json") if path.is_file()}
    if not paths or not paths >= SHARED_CONTENT:
        raise ValueError("missing content inventory or content/players.json")
    return paths


# A test whose own source names the seed script or the migrations exercises them directly
# (seed atomicity, a migration's backfill), so it keys them beyond the representatives.
DIRECT_MARKERS = {
    "scripts/seed_content.py": "seed_content",
    "scripts/migrations/**": "migrations",
}


def direct_readers(inventory, source):
    marker = DIRECT_MARKERS.get(source)
    if marker is None:
        return set()
    return {task for task, meta in inventory.items() if marker in Path(meta["path"]).read_text()}


def select_content(inventory, families, content):
    if not inventory.keys() >= SEED_REPRESENTATIVES or len(SEED_REPRESENTATIVES) > 2:
        raise ValueError("missing or excessive seed representatives")
    assignments = {task: set() for task in inventory}
    for source in content | SHARED_INPUTS:
        readers = {task for task, meta in inventory.items() if source in families[meta["family"]]["reads"]}
        for task in readers | SEED_REPRESENTATIVES | direct_readers(inventory, source):
            assignments[task].add(source)
    return assignments


def audit_content(tasks, inventory, families, content):
    for source in sorted(content | SHARED_INPUTS):
        expected = SEED_REPRESENTATIVES | direct_readers(inventory, source)
        expected |= {task for task, meta in inventory.items() if source in families[meta["family"]]["reads"]}
        receiving = {task for task in inventory if source in tasks[task]["keyed"]}
        missing_inputs = {task for task in expected if source not in tasks[task]["inputs"]}
        if receiving != expected or missing_inputs:
            raise ValueError(
                f"{source}: content coverage/input mismatch: "
                f"missing keys={sorted(expected - receiving)}, extra keys={sorted(receiving - expected)}, "
                f"missing inputs={sorted(missing_inputs)}"
            )
