"""Bun emits actual registry keys; combat aliases resolve to stems before comparison.
The reverse orphan-prompt and byte/transcode contracts remain in their focused generator and bundle suites."""

from __future__ import annotations

import functools
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

# tests/acceptance/<this file> -> parents[3] is the repo's apps/ dir.
_APPS_DIR = Path(__file__).resolve().parents[3]
_REPO_ROOT = _APPS_DIR.parents[0]
_SOUNDS_DIR = _APPS_DIR / "mobile" / "assets" / "sounds"
_MOBILE_DIR = _APPS_DIR / "mobile"
_GENERATOR_PATH = _REPO_ROOT / "scripts" / "audio" / "generate_spell_sfx.py"
_COMBAT_SOUNDS_PATH = _REPO_ROOT / "content" / "combat_sounds.json"
_ACTION_SOUNDS_PATH = _REPO_ROOT / "content" / "action_sounds.json"

# Emitter family key -> bundled subdir ("." = the flat root).
_FAMILIES = (
    ("sound", "."),
    ("music", "music"),
    ("soundscape", "soundscapes"),
    ("texture", "textures"),
)


@functools.cache
def _registry_keys() -> dict[str, list[str]]:
    """Enumerate the four TS registries in-band under bun -> {family: [keys]}.

    Skip (not fail) if bun is absent: the same enumeration also fails RED under
    `bun run test:all` via the *-registry.test.ts files, so bun-less lanes stay
    covered. Mirrors the M17 capstone's skip-if-no-bun posture.
    """
    bun = shutil.which("bun")
    if bun is None:
        pytest.skip("bun not on PATH; the registry key-sets are also guarded in `bun run test:all`")
    result = subprocess.run(
        [bun, "scripts/emit-audio-registry-keys.ts"],
        cwd=_MOBILE_DIR,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"registry-key emitter failed:\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, f"emitter printed no JSON object:\n{result.stdout}"
    return json.loads(lines[-1])


@functools.cache
def _asset_for_key() -> dict[str, str]:
    """Registry key -> the bundled stem it actually plays.

    Combat ids (story-089) and action cue ids (story-218) are ALIASES: several wire
    ids share one stem, so an alias key's own name is not a filename and never will
    be. Only the stem it resolves to has to exist on disk.
    """
    aliases: dict[str, str] = {}
    for path in (_COMBAT_SOUNDS_PATH, _ACTION_SOUNDS_PATH):
        rows = json.loads(path.read_text())
        assert rows, f"{path} is empty -- an empty alias map would read as 'no aliases'"
        aliases.update({row["id"]: row["asset"] for row in rows})
    return aliases


@functools.cache
def _load_prompts() -> dict[str, str]:
    """Import the generator PROMPTS SSOT by file path (it lives outside the agent package)."""
    spec = importlib.util.spec_from_file_location("generate_spell_sfx", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PROMPTS


@pytest.mark.parametrize("family,subdir", _FAMILIES)
def test_registry_keyset_equals_bundled_stems(family: str, subdir: str) -> None:
    keys = _registry_keys()
    registry = set(keys[family])
    assert registry, f"{family}: emitter returned no keys -- enumeration is a no-op"
    aliases = _asset_for_key() if family == "sound" else {}
    played = {aliases.get(key, key) for key in registry}
    base = _SOUNDS_DIR if subdir == "." else _SOUNDS_DIR / subdir
    bundled = {p.stem for p in base.glob("*.mp3")}
    if family == "sound":
        # An action cue may alias a texture one-shot (footstep_stone); that stem is
        # bundled under textures/, which the texture family already pins as a whole.
        textures = {p.stem for p in (_SOUNDS_DIR / "textures").glob("*.mp3")}
        alias_targets = {aliases[key] for key in registry if key in aliases}
        played -= alias_targets & (textures - bundled)
    assert played == bundled, (
        f"{family}: TS registry keys (alias-resolved) != bundled stems\n"
        f"  registry-only (missing file): {sorted(played - bundled)}\n"
        f"  disk-only (orphan asset):     {sorted(bundled - played)}"
    )


def test_every_bundled_stem_is_generatable() -> None:
    prompts = _load_prompts()
    bundled = {p.stem for p in _SOUNDS_DIR.glob("**/*.mp3")}
    ungeneratable = sorted(bundled - set(prompts))
    assert not ungeneratable, f"bundled stems with no PROMPT regenerate recipe (not generatable): {ungeneratable}"
