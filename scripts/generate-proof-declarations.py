"""Generate per-file deterministic acceptance tasks and shared-file representatives."""

import ast
import fnmatch
import json
import os
import subprocess
from pathlib import Path

ROOT = Path.cwd()
TESTS = Path("apps/agent/tests/acceptance")
ROOTS = ["apps/agent", "apps/agent/tests", "scripts"]
CONFTESTS = ["apps/agent/tests/conftest.py", str(TESTS / "conftest.py")]
PAID = {"real_llm", "openai_real_llm", "live_voice"}
MARKERS = "acceptance and not real_llm and not openai_real_llm and not live_voice"


def paid_only(path):
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            return any(isinstance(n, ast.Attribute) and n.attr in PAID for n in ast.walk(node.value))
    return False


def imports(path):
    return {"imports-of": path, "python-path": ROOTS}


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
    exempt = {p for p in root["exempt"] if p.startswith(str(TESTS))}
    if paid != exempt:
        raise ValueError(f"paid-only files differ from root exemptions: {sorted(paid ^ exempt)}")
    entries = [str(p) for p in tests if str(p) not in paid]
    if len({Path(p).stem for p in entries}) != len(entries):
        raise ValueError("duplicate acceptance stems")
    shared = set().union(*(graph[p]["closure"] for p in CONFTESTS))
    keyed = {p: set() for p in entries}
    for file in sorted(shared):
        candidates = [p for p in entries if file in graph[p]["direct"]]
        if not candidates:
            candidates = [p for p in entries if file in graph[p]["closure"] or file in shared]
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
    tasks = {}
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
                inputs.append({"imports-of": f"apps/mobile/src/__tests__/{target}"})
        if "inventory-db-bridge" in closure_text or "_inventory_bridge" in closure_text:
            inputs += [
                {"imports-of": "apps/mobile/scripts/inventory-db-bridge.ts"},
                {"imports-of": "apps/mobile/test-preload.ts"},
            ]
        if "apps/agent/tests/agent_tool_profiles.py" in graph[path]["closure"]:
            inputs += [imports(str(p)) for p in sorted(Path("apps/agent").glob("*_agent.py"))]
        tasks[f"agent-acceptance:{Path(path).stem}"] = {
            "run": f"ALLOW_PAID_TESTS= REQUIRE_REAL_LLM= uv run --frozen --directory apps/agent pytest {path.removeprefix('apps/agent/')} -q -m '{MARKERS}'",
            "sets": ["sprint"],
            "needs": ["acceptance-stack"],
            "links": ["node_modules"],
            "inputs": inputs,
            "keyed": sorted(keyed[path] | (stack_keyed)),
        }
    # Root unkeyed policy must preserve the existing Bun tasks and the full unit key.
    for name, task in json.loads(Path("scripts/proof-bun-tasks.json").read_text()).items():
        tasks[name] = {**task, "keyed": sorted(shared)}
    tasks["agent-pytest"] = {
        "run": "ALLOW_PAID_TESTS= REQUIRE_REAL_LLM= uv run --frozen --directory apps/agent pytest tests/ -q -m 'not acceptance' -n 8",
        "sets": ["land"],
        "needs": ["agent-db"],
        "links": ["node_modules"],
        "inputs": [
            "apps/agent/**",
            "apps/mobile/assets/**",
            "assets/**",
            "!apps/agent/tests/acceptance/**/test_*.py",
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
        "keyed": sorted(shared),
    }
    output = {"unkeyed": sorted(shared), "tasks": tasks}
    (Path(os.environ["PROOF_DECLARATIONS"]) / "python.yaml").write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
