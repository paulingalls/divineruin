"""Generate per-file deterministic acceptance tasks and shared-file representatives."""

import ast
import fnmatch
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path.cwd()
TESTS = Path("apps/agent/tests/acceptance")
ROOTS = ["apps/agent", "apps/agent/tests", "scripts"]
CONFTESTS = ["apps/agent/tests/conftest.py", str(TESTS / "conftest.py")]
PAID = {"real_llm", "openai_real_llm", "live_voice"}
MARKERS = "acceptance and not real_llm and not openai_real_llm and not live_voice"


def paid_only(path):
    value = None
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            if value is not None:
                raise ValueError(f"{path}: unsupported pytestmark reassignment")
            value = node.value
        elif (
            isinstance(node, (ast.AnnAssign, ast.AugAssign))
            and isinstance(node.target, ast.Name)
            and node.target.id == "pytestmark"
        ):
            raise ValueError(f"{path}: unsupported pytestmark assignment")
    if value is None:
        return False
    markers = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
    names = set()
    for marker in markers:
        target = marker.func if isinstance(marker, ast.Call) else marker
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "pytest"
        ):
            raise ValueError(f"{path}: unsupported pytestmark expression")
        names.add(target.attr)
    return bool(names & PAID)


def imports(path):
    return {"imports-of": path, "python-path": ROOTS}


def partitions(path):
    tree = ast.parse(Path(path).read_text())
    if Path(path).stem == "test_choir_capstone":
        names = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                raise ValueError(f"{path}: unsupported collected class")
            if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                (a.asname or a.name).startswith(("test_", "Test")) for a in node.names
            ):
                raise ValueError(f"{path}: unsupported imported test")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                names.append(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id.startswith("test_") for t in targets):
                    raise ValueError(f"{path}: unsupported collected assignment")
        if not names:
            raise ValueError(f"{path}: no tests")
        return [(name, "::" + name, "") for name in names]
    if Path(path).stem == "test_terrain_commands":
        values = [
            ast.literal_eval(n.value)
            for n in tree.body
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TERRAINS" for t in n.targets)
        ]
        if len(values) != 1 or len(values[0]) < 6:
            raise ValueError(f"{path}: expected TERRAINS partition")
        names = [row[0] for row in values[0]]
        if any(not isinstance(n, str) or not n.isidentifier() for n in names) or len(set(names)) != len(names):
            raise ValueError(f"{path}: unsupported terrain names")
        a, b = " or ".join(names[:5]), " or ".join(names[5:])
        return [
            ("a", "", f" -k {shlex.quote('(' + a + ')')}"),
            ("b", "", f" -k {shlex.quote('(' + b + ') and not (' + a + ')')}"),
            ("other", "", f" -k {shlex.quote('not (' + a + ' or ' + b + ')')}"),
        ]
    return [("", "", "")]


def e2e_tasks(shared=(), stack_keyed=()):
    specs = sorted(Path("e2e/specs").glob("*.e2e.ts"))
    groups = {
        "home-character": (
            "chromium",
            [p for p in specs if p.name == "home-character.e2e.ts"],
        ),
        "chromium": (
            "chromium",
            [p for p in specs if not p.name.startswith("web-") and p.name != "home-character.e2e.ts"],
        ),
        "web": (
            "web",
            [p for p in specs if p.name.startswith("web-") and p.name != "web-production.e2e.ts"],
        ),
        "web-lighthouse": (
            "web-lighthouse",
            [p for p in specs if p.name == "web-production.e2e.ts"],
        ),
    }
    tasks = {}
    for part, (project, files) in groups.items():
        if not files:
            raise ValueError(f"empty e2e partition: {part}")
        inputs = [
            *[{"imports-of": str(p)} for p in files],
            {"imports-of": "e2e/playwright.config.ts"},
            "$stack",
            "$bun-config",
            "scripts/proof-e2e.sh",
            "scripts/proof-db-clone.ts",
            "e2e/package.json",
            "e2e/bun.lock",
            "e2e/tsconfig.json",
            "apps/server/src/**",
            "apps/server/package.json",
            "apps/server/tsconfig.json",
            "apps/server/bunfig.toml",
            "packages/**",
            "$e2e-home-character-represents",
            "content/**",
            "!**/*.test.*",
        ]
        if project == "chromium":
            inputs += [
                {"imports-of": "e2e/global-setup.ts"},
                "apps/mobile/src/**",
                "apps/mobile/assets/**",
                "apps/mobile/app.json",
                "apps/mobile/package.json",
                "apps/mobile/tsconfig.json",
                "apps/mobile/metro.config.js",
                "assets/**",
                ".watchmanconfig",
                "!apps/mobile/src/__tests__/**",
            ]
        else:
            inputs += [
                "apps/web/src/**",
                "apps/web/scripts/**",
                "apps/web/public/**",
                "apps/web/index.html",
                "apps/web/package.json",
                "apps/web/tsconfig.json",
                "apps/audio/**",
            ]
        if part == "chromium":
            inputs += [
                {
                    "imports-of": "e2e/fixtures/inventory-snapshot.py",
                    "python-path": ["apps/agent"],
                },
                "apps/agent/pyproject.toml",
                "apps/agent/uv.lock",
                "apps/agent/.python-version",
            ]
        # Anchors prevent the chromium remainder from also matching home-character.
        filters = " ".join(shlex.quote("/" + p.name.replace(".", r"\.") + "$") for p in files)
        tasks[f"e2e:{part}"] = {
            "run": f"bash scripts/proof-e2e.sh {part} --project={project} {filters}",
            "sets": ["sprint"],
            "lane": "e2e",
            "needs": ["e2e-stack"],
            "links": ["node_modules", "e2e/node_modules"],
            "inputs": inputs,
            "keyed": [
                *sorted(shared if part == "chromium" else stack_keyed),
                *(["packages/shared/**"] if part == "home-character" else []),
            ],
        }
    return tasks


def main():
    paths = sorted(str(p) for root in (Path("apps/agent"), Path("scripts")) for p in root.rglob("*.py"))
    result = subprocess.run(
        ["bun", "scripts/proof-python-closure.ts"],
        input=json.dumps(paths),
        text=True,
        capture_output=True,
        check=True,
    )
    graph = json.loads(result.stdout)
    tests = sorted(TESTS.rglob("test_*.py"))
    paid = {str(p) for p in tests if paid_only(p)}
    # Bun already owns the YAML parser; avoid a generator-only Python dependency.
    parsed = subprocess.run(
        [
            "bun",
            "-e",
            'console.log(JSON.stringify(Bun.YAML.parse(await Bun.file("proof.yaml").text())))',
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    root = json.loads(parsed.stdout)
    entries = [str(p) for p in tests if str(p) not in paid]
    if len({Path(p).stem for p in entries}) != len(entries):
        raise ValueError("duplicate acceptance stems")
    shared = set().union(*(graph[p]["closure"] for p in CONFTESTS))
    keyed = {p: set() for p in entries}
    for file in sorted(shared):
        candidates = [p for p in entries if file in graph[p]["direct"]]
        if not candidates:
            candidates = [p for p in entries if file in graph[p]["closure"]] or entries
            limit = 1
        else:
            limit = 3
        representatives = sorted(candidates, key=lambda p: (len(graph[p]["closure"]), p))[:limit]
        if not representatives:
            raise ValueError(f"no representative for {file}")
        for p in representatives:
            keyed[p].add(file)

    def stack_patterns(name):
        return [
            p for item in root["inputs"][name] for p in (stack_patterns(item[1:]) if item.startswith("$") else [item])
        ]

    stack_keyed = {
        p
        for p in shared
        if any(
            fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.replace("/**/", "/")) for pat in stack_patterns("stack")
        )
    }
    tasks = e2e_tasks(shared, stack_keyed)
    for path in entries:
        conftests = [
            str(p / "conftest.py")
            for p in Path(path).parents
            if str(p).startswith(str(TESTS)) and (p / "conftest.py").exists()
        ]
        inputs = [
            imports(path),
            *[
                imports(f"apps/agent/{module}.py")
                for module in (
                    "creation_tools",
                    "db_mutations_companion",
                    "companion_relationship_queries",
                    "combat_agent",
                )
            ],
            "packages/shared/fixtures/**",
            imports(CONFTESTS[0]),
            *[imports(p) for p in conftests],
            "$stack",
            "apps/agent/pyproject.toml",
            "apps/agent/uv.lock",
            "apps/agent/.python-version",
            "apps/agent/tests/acceptance/**/*.feature",
            "apps/agent/tests/fixtures/**",
            "apps/agent/tests/acceptance/fixtures/**",
            "apps/mobile/assets/**",
            "apps/audio/**",
            "content/**",
        ]
        closure_text = "\n".join(Path(p).read_text() for p in graph[path]["closure"])
        if "subprocess" in closure_text or "spec_from_file_location" in closure_text or "run_path" in closure_text:
            inputs += [
                "scripts/**/*.py",
                "scripts/**/*.ts",
                "apps/mobile/scripts/**",
                "apps/mobile/src/audio/**",
                "apps/mobile/tsconfig.json",
                "apps/mobile/package.json",
                "apps/mobile/bunfig.toml",
                "apps/server/**",
                "packages/shared/**",
                "assets/**",
                "docs/**",
                "$bun-config",
            ]
        if "async-activity-reset.md" in closure_text:
            inputs.append("docs/ops/async-activity-reset.md")
        for target in ("use-game-events.parse.test.ts", "sound-registry.test.ts"):
            if target in closure_text:
                inputs += [
                    {"imports-of": f"apps/mobile/src/__tests__/{target}"},
                    {"imports-of": "apps/mobile/test-preload.ts"},
                ]
        if "inventory-db-bridge" in closure_text or "_inventory_bridge" in closure_text:
            inputs += [
                {"imports-of": "apps/mobile/scripts/inventory-db-bridge.ts"},
                {"imports-of": "apps/mobile/test-preload.ts"},
            ]
        if "apps/agent/tests/agent_tool_profiles.py" in graph[path]["closure"]:
            inputs += [imports(str(p)) for p in sorted(Path("apps/agent").glob("*_agent.py"))]
        task = {
            "run": f"ALLOW_PAID_TESTS= REQUIRE_REAL_LLM= uv run --frozen --directory apps/agent pytest {path.removeprefix('apps/agent/')} -q -m '{MARKERS}'",
            "sets": ["sprint"],
            "needs": ["acceptance-stack"],
            "links": ["node_modules"],
            "inputs": inputs,
            "keyed": [*sorted(keyed[path] | stack_keyed), "packages/shared/**"],
        }
        for suffix, selector, expression in partitions(path):
            part = dict(task)
            part["run"] = (
                task["run"].replace(
                    path.removeprefix("apps/agent/"),
                    path.removeprefix("apps/agent/") + selector,
                )
                + expression
            )
            tasks[f"agent-acceptance:{Path(path).stem}" + (f":{suffix}" if suffix else "")] = part
    # Root unkeyed policy must preserve the existing Bun tasks and the full unit key.
    for name, task in json.loads(Path("scripts/proof-bun-tasks.json").read_text()).items():
        tasks[name] = {**task, "keyed": [*sorted(shared), "packages/shared/**"]}
    tasks["agent-pytest"] = {
        "run": "ALLOW_PAID_TESTS= REQUIRE_REAL_LLM= uv run --frozen --directory apps/agent pytest tests/ -q -m 'not acceptance' -n 8",
        "sets": ["land"],
        "needs": ["agent-db"],
        "links": ["node_modules"],
        "inputs": [
            "apps/agent/**",
            "apps/mobile/assets/**",
            "assets/**",
            ".env.example",
            "apps/audio/**",
            "apps/mobile/src/__tests__/fixtures/**",
            "apps/mobile/tsconfig.json",
            "apps/mobile/package.json",
            "apps/mobile/bunfig.toml",
            "content/**",
            "scripts/**/*.py",
            "apps/**/*.{ts,tsx}",
            "packages/**",
            "e2e/**",
            "scripts/**",
            "docs/**",
            "$stack",
            "$bun-config",
        ],
        "keyed": [*sorted(shared), "packages/shared/**"],
    }
    for task in tasks.values():
        expanded = []
        for item in task["inputs"]:
            path = item.get("imports-of") if isinstance(item, dict) else None
            if path in graph and graph[path].get("reason"):
                # Dynamic registry discovery needs the whole Python corpus, not a false import proof.
                expanded += [*graph[path]["closure"], "apps/agent/**/*.py"]
            else:
                expanded.append(item)
        task["inputs"] = expanded
    output = {"unkeyed": sorted(shared), "tasks": tasks}
    (Path(os.environ["PROOF_DECLARATIONS"]) / "python.yaml").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
