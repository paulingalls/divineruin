"""Inventory harness data, select its readers, and audit effective coverage."""

import json
import re
import subprocess
from pathlib import Path

from proof_family_selection import NON_PYTHON, audit_readers, select_readers

DATA_PATTERNS = (
    "apps/agent/tests/acceptance/**/*.feature",
    "apps/agent/tests/fixtures/**",
    "apps/agent/tests/acceptance/fixtures/**",
    "packages/shared/fixtures/**",
)
PROVIDER_HARNESS = {
    "apps/agent/tests/_db_lifecycle.py",
    "apps/agent/tests/acceptance/_postgres_fixtures.py",
    "apps/agent/tests/acceptance/_livekit.py",
    "scripts/worktree-common.sh",
}


def data_inventory():
    paths = set()
    for pattern in DATA_PATTERNS:
        # Before Python 3.13 a trailing ** matches only directories; **/* matches files everywhere.
        matches = Path().glob(pattern + "/*" if pattern.endswith("/**") else pattern)
        found = {str(p) for p in matches if p.is_file()}
        if not found:
            raise ValueError(f"empty harness data inventory: {pattern}")
        paths.update(found)
    names = {}
    for path in sorted(paths):
        name = Path(path).name
        if name in names:
            raise ValueError(f"ambiguous harness data basename: {names[name]}, {path}")
        names[name] = path
    for path in NON_PYTHON | PROVIDER_HARNESS:
        if not Path(path).is_file():
            raise ValueError(f"missing harness source: {path}")
    return paths


def named_readers(inventory, paths):
    modules = {m["path"] for m in inventory.values()}
    modules.update(p for m in inventory.values() for p in m["closure"] if p.startswith("apps/agent/tests/"))
    texts = {p: Path(p).read_text() for p in modules}
    readers = {}
    for source in paths:
        marker = re.compile(r"(?<![\w])" + re.escape(Path(source).name) + r"(?![\w])")
        naming = {p for p, text in texts.items() if marker.search(text)}
        direct = {t for t, m in inventory.items() if m["path"] in naming}
        helpers = {
            p: {t for t, m in inventory.items() if p in m["closure"] and m["path"] != p}
            for p in naming
            if p.startswith("apps/agent/tests/")
        }
        readers[source] = (direct, helpers)
    return readers


def add_provider_readers(inventory):
    for meta in inventory.values():
        meta["closure"].update(PROVIDER_HARNESS)
    for source, (direct, helpers) in named_readers(inventory, NON_PYTHON - PROVIDER_HARNESS).items():
        for task in direct | set().union(*helpers.values(), set()):
            inventory[task]["closure"].add(source)


def select_named(inventory, readers):
    assignments = {t: set() for t in inventory}
    for source, (direct, helpers) in readers.items():
        selected = set(direct)
        for helper, reaching in helpers.items():
            representatives = select_readers(inventory, helper, reaching, 1)
            selected.update(representatives)
        for task in selected:
            assignments[task].add(source)
    return assignments


def audit_named(tasks, inventory, readers):
    for source, (direct, helpers) in readers.items():
        receiving = {t for t in inventory if source in tasks[t]["keyed"] and source in tasks[t]["inputs"]}
        allowed = direct | set().union(*helpers.values(), set())
        if receiving - allowed or direct - receiving:
            raise ValueError(
                f"{source}: named reader mismatch: missing={sorted(direct - receiving)}, extra={sorted(receiving - allowed)}"
            )
        for helper, reaching in helpers.items():
            # Other helpers and direct readers may legitimately select additional tasks.
            others = direct | set().union(*(r for p, r in helpers.items() if p != helper), set())
            audit_readers(
                source,
                inventory,
                reaching,
                receiving & reaching,
                receiving & others & reaching,
                1,
            )


def audit_nonempty(tasks, sources, input_groups, graph):
    def expand(items):
        patterns = []
        for item in items:
            if isinstance(item, dict):
                entry = item["imports-of"]
                patterns.extend(graph[entry]["closure"] if entry in graph else [entry])
            elif item.startswith("$"):
                patterns.extend(expand(input_groups[item[1:]]))
            else:
                patterns.append(item)
        return patterns

    # Use Proof's glob implementation; Python glob syntax differs on braces and **.
    result = subprocess.run(
        [
            "bun",
            "-e",
            """
        const {tasks, sources} = await Bun.stdin.json();
        const receivers = Object.fromEntries(sources.map(p => [p, []]));
        for (const [name, task] of Object.entries(tasks)) {
            const inputs = task.inputs.map(p => [p.startsWith('!'), new Bun.Glob(p.replace(/^!/, ''))]);
            const keys = task.keyed.map(p => new Bun.Glob(p));
            for (const path of sources) {
                let delivered = false;
                for (const [negative, glob] of inputs) if (glob.match(path)) delivered = !negative;
                if (delivered && keys.some(g => g.match(path))) receivers[path].push(name);
            }
        }
        console.log(JSON.stringify(receivers));
        """,
        ],
        input=json.dumps(
            {
                "sources": sorted(sources),
                "tasks": {
                    name: {"inputs": expand(task["inputs"]), "keyed": task["keyed"]} for name, task in tasks.items()
                },
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    for source, receivers in json.loads(result.stdout).items():
        if not receivers:
            raise ValueError(f"orphan harness/data source: {source}: no effective keyed receiver")
