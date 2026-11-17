"""Resolve runtime Python roots and assign family-owned acceptance keys."""

import ast
import json
import re
from pathlib import Path

from proof_content_sql import seed_tables, sql_reads

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


# DB readers are explicit: importing db alone does not establish a catalog read.
CONTENT_LOADERS = {
    "action_sounds": ("action_sound_content",),
    "combat_sounds": ("combat_sound_content",),
    "archetype_abilities": ("abilities",),
    "archetype_milestones": ("milestones",),
    "archetypes": ("archetypes",),
    "companions": ("companion_profiles",),
    "creatures": ("creature_catalog",),
    "encounter_templates": ("db_content_queries",),
    "errand_templates": ("db_content_queries",),
    "factions": ("db_content_queries",),
    "locations": ("db_content_queries",),
    "lore_entries": ("db_content_queries",),
    "scenes": ("db_content_queries",),
    "training_programs": ("db_content_queries",),
    "gathering_nodes": ("db_content_queries", "db_mutations_gathering"),
    "items": ("db_content_queries", "db_queries", "db_inventory_snapshot"),
    "materials_catalog": (
        "materials",
        "db_content_queries",
        "db_queries",
        "db_inventory_snapshot",
    ),
    "npcs": ("npcs", "db_content_queries", "db_queries"),
    "npc_state": ("db_queries",),
    "quests": ("db_content_queries", "db_queries"),
    "loot_tables": ("db_content_queries", "creature_schema"),
    "gods": ("_gods_content",),
    "mentor_variants": ("mentor_variants",),
    "pricing": ("pricing_queries",),
    "quality_outcomes": ("quality_outcomes",),
    "racial_resonance_bonuses": ("racial_resonance",),
    "recipes": ("recipes",),
    "role_archetypes": ("role_archetypes",),
    "settlement_templates": ("settlement_templates",),
    "spells": ("spells",),
    "training_activity_types": ("training_rules", "purification_tools"),
    "events": (),
    "inventory_pools": (),
    "level_progression": (),
    "voice_registry": (),
}
CONTENT_LOADERS = {
    f"content/{name}.json": {f"apps/agent/{module}.py" for module in modules}
    for name, modules in CONTENT_LOADERS.items()
}
SERVER_CATALOGS = {
    f"content/{name}.json"
    for name in (
        "locations",
        "spells",
        "training_activity_types",
        "training_programs",
        "errand_templates",
        "recipes",
        "items",
        "archetypes",
        "archetype_abilities",
        "mentor_variants",
        "role_archetypes",
        "archetype_milestones",
        "pricing",
    )
}
CONTENT_FIXTURES = {
    "conftest.py",
    "_postgres_fixtures.py",
    "_db_lifecycle.py",
    "_livekit.py",
}


def behavioral_closure(entry, graph):
    pending, found = [entry], set()
    while pending:
        path = pending.pop()
        if path in found or Path(path).name in CONTENT_FIXTURES:
            continue
        if path not in graph:
            raise ValueError(f"{entry}: missing behavioral Python root {path}")
        found.add(path)
        pending.extend(set(graph[path]["direct"]) - found)
        pending.extend(explicit_roots(path, graph) - found)
    return found


def content_literals(path, content):
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                body.pop(0)
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return {source for source in content if source in literals or Path(source).name in literals}


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
    behavioral, literals = {}, {}
    content = content_inventory()

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
        if entry in graph:
            if entry not in behavioral:
                behavioral[entry] = behavioral_closure(entry, graph)
            for module in behavioral[entry]:
                if module not in literals:
                    literals[module] = content_literals(module, content)
        inventory[task] = {
            "content_closure": behavioral.get(entry, set()),
            "content_direct": literals.get(entry, set()) | (sql_reads(entry, content) if entry in graph else set()),
            "content_reads": set().union(*(literals[p] for p in behavioral.get(entry, set())), set()),
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
                if not shared and (family not in owners or reaching):
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
            if not shared and (family not in owners or reaching):
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


def content_readers(inventory, families, content):
    if not content >= SHARED_CONTENT or not inventory or not inventory.keys() >= SEED_REPRESENTATIVES:
        raise ValueError("empty content/task inventory or missing seed representatives")
    if len(SEED_REPRESENTATIVES) > 2:
        raise ValueError("excessive seed representatives")
    if missing := (content - SHARED_CONTENT) - CONTENT_LOADERS.keys():
        raise ValueError(f"content has no behavioral loader mapping: {sorted(missing)}")
    for source, roots in CONTENT_LOADERS.items():
        if source not in content or any(not Path(p).is_file() for p in roots):
            raise ValueError(f"{source}: absent content or loader: {sorted(roots)}")
    seeded = {f"content/{name}" for name in seed_tables()}
    if missing := seeded - content:
        raise ValueError(f"seed TABLE_MAP names absent content: {sorted(missing)}")
    readers = {}
    for source in content:
        if source in SHARED_CONTENT:
            readers[source] = set()
            continue
        if not any(source in family["reads"] for family in families.values()):
            raise ValueError(f"content has no reader family: {source}")
        roots = CONTENT_LOADERS[source] | ({"scripts/seed_content.py"} if source in seeded else set())
        if source in SERVER_CATALOGS:
            roots |= {"apps/agent/tests/acceptance/_server.py"}
        if any(not Path(p).is_file() for p in roots):
            raise ValueError(f"{source}: missing behavioral loader: {sorted(roots)}")
        readers[source] = {
            t
            for t, m in inventory.items()
            if source in m["content_direct"]
            or (
                source in families[m["family"]]["reads"]
                and (roots & m["content_closure"] or source in m["content_reads"] or m["family"] == "mobile-e2e")
            )
        }
    return readers


def select_content(inventory, families, content):
    assignments = {task: set() for task in inventory}
    readers = content_readers(inventory, families, content)
    for source in content | SHARED_INPUTS:
        reaching = readers.get(source, set())
        selected = SEED_REPRESENTATIVES | direct_readers(inventory, source)
        selected |= {t for t in reaching if source in inventory[t]["content_direct"]}
        if sum(t.startswith("agent-acceptance:") for t in reaching) <= 10:
            selected |= reaching
        else:
            for family in {inventory[t]["family"] for t in reaching}:
                members = {t for t in reaching if inventory[t]["family"] == family}
                if not selected & members:
                    selected.add(first_reader(inventory, members))
        for task in selected:
            assignments[task].add(source)
    return assignments


def audit_content(tasks, inventory, families, content):
    readers = content_readers(inventory, families, content)
    for source in sorted(content | SHARED_INPUTS):
        reaching = readers.get(source, set())
        required = SEED_REPRESENTATIVES | direct_readers(inventory, source)
        required |= {t for t in reaching if source in inventory[t]["content_direct"]}
        for field in ("keyed", "inputs"):
            receiving = {t for t in inventory if source in tasks[t][field] and source in tasks[t]["keyed"]}
            audit_readers(source, inventory, reaching, receiving, required, 1)
            if sum(t.startswith("agent-acceptance:") for t in reaching) > 10:
                for family in {inventory[t]["family"] for t in reaching}:
                    members = {t for t in reaching if inventory[t]["family"] == family}
                    if required & members and (receiving - required) & members:
                        raise ValueError(f"{source}: family {family}: redundant {field} representative")
