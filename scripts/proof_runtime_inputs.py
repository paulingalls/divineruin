"""Repository launches and committed media readers, separate from sandbox delivery."""

import ast
import json
from collections import Counter
from functools import cache
from pathlib import Path, PurePosixPath

from proof_family_selection import first_reader

ACCEPTANCE = "apps/agent/tests/acceptance/"
LAUNCH_CALLS = json.loads(Path("scripts/proof-launch-calls.json").read_text())
LAUNCHES = {
    module: sorted({root for site in sites for root in site["roots"]})
    for module, sites in LAUNCH_CALLS.items()
    if any(site["roots"] for site in sites)
}
CALLS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "asyncio.create_subprocess_shell",
    "os.system",
    "asyncio.create_subprocess_exec",
    "importlib.util.spec_from_file_location",
    "runpy.run_path",
}
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
# Preserve the existing full-key configuration memberships independently of source selection.
CONFIG = [
    "apps/mobile/tsconfig.json",
    "apps/mobile/package.json",
    "apps/mobile/bunfig.toml",
    "apps/server/package.json",
    "apps/server/tsconfig.json",
    "apps/server/bunfig.toml",
    "packages/shared/package.json",
    "packages/shared/tsconfig.json",
    "$bun-config",
]


@cache
def calls(path):
    nodes = list(ast.walk(ast.parse(Path(path).read_text())))
    alias = {a.asname: a.name for n in nodes if isinstance(n, ast.Import) for a in n.names if a.asname}
    names = {f"{n.module}.{a.name}" for n in nodes if isinstance(n, ast.ImportFrom) for a in n.names}
    for n in nodes:
        if isinstance(n, ast.Call):
            head, dot, rest = ast.unparse(n.func).partition(".")
            names.add(alias.get(head, head) + dot + rest)
    return names & CALLS


def target_bindings(call, tree):
    # Launch targets may be assembled outside the call (cwd, eval script, command path).
    expressions = [*call.args, *(k.value for k in call.keywords if k.arg == "cwd")]
    names = {n.id for expression in expressions for n in ast.walk(expression) if isinstance(n, ast.Name)}
    bindings = set()
    pending = list(names)
    assignments = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))]
    while pending:
        name = pending.pop()
        for node in assignments:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(n, ast.Name) and n.id == name for t in targets for n in ast.walk(t)):
                continue
            bindings.add(ast.unparse(node))
            dependencies = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            pending.extend(dependencies - names)
            names.update(dependencies)
    return tuple(sorted(bindings))


@cache
def launch_sites(path):
    tree = ast.parse(Path(path).read_text())
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update({a.asname or a.name: a.name for a in node.names})
        elif isinstance(node, ast.ImportFrom):
            aliases.update({a.asname or a.name: f"{node.module}.{a.name}" for a in node.names})
    sites = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        head, dot, rest = ast.unparse(node.func).partition(".")
        name = aliases.get(head, head) + dot + rest
        if name in CALLS:
            node.func = ast.parse(name, mode="eval").body
            sites[(ast.unparse(node), target_bindings(node, tree))] += 1
    return sites


def audit_launches(modules):
    for module in sorted(modules):
        actual = launch_sites(module)
        declarations = LAUNCH_CALLS.get(module, [])
        for site in declarations:
            if not site["reason"] or any(not Path(root).is_file() for root in site["roots"]):
                raise ValueError(f"{module}: invalid launch classification: {site}")
        expected = Counter((site["call"], tuple(site["bindings"])) for site in declarations)
        if extra := actual - expected:
            raise ValueError(f"unclassified repository launch/load: {module}: {dict(extra)}")
        if missing := expected - actual:
            raise ValueError(f"{module}: stale launch classification: {dict(missing)}")


def runtime_inputs(inventory, runtime):
    readers = {}
    audit_launches({module for meta in inventory.values() for module in meta["closure"] if module.endswith(".py")})
    for module, roots in LAUNCHES.items():
        paths = set().union(*(set(runtime[root]) for root in roots))
        for path in paths:
            # Fixtures call seed(), but only main() launches the Bun validators.
            callers = {ACCEPTANCE + "test_seed_atomic.py", ACCEPTANCE + "test_seed_content_cache.py"}
            readers.setdefault(path, set()).update(callers if module == "scripts/seed_catalogs.py" else {module})
    media = {
        str(p)
        for root in ("apps/mobile/assets", "apps/audio", "assets")
        for p in Path(root).rglob("*")
        if p.is_file() and not any(x.startswith(".") for x in p.parts)
    }
    for path in media:
        modules = readers.setdefault(path, set())
        if path.startswith("apps/mobile/assets/sounds/"):
            modules.add(ACCEPTANCE + "test_m22_audio_completeness_capstone.py")
            if Path(path).parent == Path("apps/mobile/assets/sounds"):
                modules.update(
                    {
                        ACCEPTANCE + "test_m17_spell_sfx_capstone.py",
                        "apps/agent/action_sound_content.py",
                    }
                )
            if path.startswith("apps/mobile/assets/sounds/textures/"):
                modules.add("apps/agent/action_sound_content.py")
        if path == "assets/audio/prologue.mp3":
            modules.add("apps/agent/prologue.py")
        if path.startswith("assets/images/"):
            modules.update(
                module
                for module, roots in LAUNCHES.items()
                if any("apps/server/src/image-dir.ts" in runtime[root] for root in roots)
            )
    return {p: m for p, m in readers.items() if m and not any(PurePosixPath(p).full_match(g) for g in FULL_KEY)}


def assign_runtime(tasks, inventory, runtime):
    readers = runtime_inputs(inventory, runtime)
    reached = set().union(*({m["path"]} | m["closure"] for m in inventory.values()))
    for path, modules in readers.items():
        if stale := modules - reached:
            raise ValueError(f"{path}: named reader reaches no task: {sorted(stale)}")
        direct = {t for t, m in inventory.items() if m["path"] in modules}
        reaching = {t for t, m in inventory.items() if modules & m["closure"]}
        selected = set(direct)
        # Image bytes are read on endpoint calls; Expo owns that path, not each server-testing family.
        if path.startswith("assets/images/"):
            reaching = set()
        for family in {inventory[t]["family"] for t in reaching}:
            members = {t for t in reaching if inventory[t]["family"] == family}
            if not selected & members:
                preferred = {t for t in members if modules & inventory[t]["preferred"]}
                selected.add(first_reader(inventory, preferred or members))
        for task in selected:
            tasks[task]["keyed"].append(path)
            tasks[task]["inputs"].append(path)
    return set(readers)
