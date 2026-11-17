"""Repository launches and committed media readers, separate from sandbox delivery."""

import ast
from functools import cache
from pathlib import Path, PurePosixPath

from proof_family_selection import first_reader

ACCEPTANCE = "apps/agent/tests/acceptance/"
LAUNCHES = {
    "scripts/seed_catalogs.py": ["scripts/seed_catalogs.ts", "scripts/seed_cache.ts"],
    ACCEPTANCE + "_server.py": ["apps/server/src/index.ts"],
    ACCEPTANCE + "test_leave_summary.py": ["apps/server/src/session-room-process.fixture.ts"],
    ACCEPTANCE + "test_inventory_taint_migration.py": ["scripts/migrate.ts"],
    ACCEPTANCE + "test_combat_spatial_entry.py": ["packages/shared/src/entities/encounter.ts"],
    ACCEPTANCE + "test_live_material_inventory.py": [
        "apps/mobile/src/__tests__/use-game-events.parse.test.ts",
        "apps/mobile/test-preload.ts",
    ],
    ACCEPTANCE + "test_m17_spell_sfx_capstone.py": [
        "apps/mobile/src/__tests__/sound-registry.test.ts",
        "apps/mobile/test-preload.ts",
    ],
    ACCEPTANCE + "test_m22_audio_completeness_capstone.py": ["apps/mobile/scripts/emit-audio-registry-keys.ts"],
}
CLASSIFIED = {
    "apps/agent/tts_prerender.py",
    "apps/agent/tests/_repo_inventory.py",
    "apps/agent/tests/_db_lifecycle.py",
    ACCEPTANCE + "_livekit.py",
    ACCEPTANCE + "test_m22_audio_completeness_capstone.py",
}
CALLS = {
    "subprocess.run",
    "subprocess.Popen",
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
    return {ast.unparse(n.func) for n in ast.walk(ast.parse(Path(path).read_text())) if isinstance(n, ast.Call)} & CALLS


def runtime_inputs(inventory, runtime):
    readers = {}
    for meta in inventory.values():
        for module in meta["closure"]:
            if module.endswith(".py") and calls(module) and module not in LAUNCHES and module not in CLASSIFIED:
                raise ValueError(f"unclassified repository launch/load: {module}")
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
    for path, modules in readers.items():
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
