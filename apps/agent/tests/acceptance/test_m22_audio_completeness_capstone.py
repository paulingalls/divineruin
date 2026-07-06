"""M22 capstone: the audio-completeness chain, end-to-end.

Proves the full audio pipeline holds together and closes the "ALL game audio is
generatable" intent. The one completeness hole no other test spans is a
cross-language mismatch between the four mobile TS registries and the bundled
assets: a bundled asset wired to no registry (orphan asset), or a registry key
with no asset (missing file). This capstone enumerates every registry key
in-band under bun (via scripts/emit-audio-registry-keys.ts) and asserts, per
family, that the registry key-set exactly equals the bundled stem-set — then
ties the whole set to the generator PROMPTS SSOT (generatable) with no .wav.

Pure filesystem + bun; NO Postgres (AC3 amended — the DB spell-catalog half is
owned by test_m17_spell_sfx_capstone.py). Lives in the acceptance lane for the
cross-language bun subprocess + end-to-end roll-up, not a DB.

Not re-asserted here (owned elsewhere, dedup):
- bundled<->PROMPT parity, both directions -> apps/agent/tests/test_generate_spell_sfx.py
- source==bundled byte-equality -> apps/agent/tests/test_audio_bundle_compressed.py (story-006)
- per-stem transcode signature (44.1kHz/<=160kbps) -> test_audio_bundle_compressed.py
"""

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

# Emitter family key -> bundled subdir ("." = the flat root: 20 legacy + 7 spell).
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
def _load_prompts() -> dict[str, str]:
    """Import the generator PROMPTS SSOT by file path (it lives outside the agent package)."""
    spec = importlib.util.spec_from_file_location("generate_spell_sfx", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PROMPTS


@pytest.mark.parametrize("family,subdir", _FAMILIES)
def test_registry_keyset_equals_bundled_stems(family: str, subdir: str) -> None:
    """The novel cross-language completeness assertion: every family's TS-registry

    key-set exactly equals its bundled <dir>/*.mp3 stem-set. Catches a missing
    file (registry key with no asset) AND an orphan asset (bundled file wired to
    no registry) -- the direction no existing guard spans.
    """
    keys = _registry_keys()
    registry = set(keys[family])
    assert registry, f"{family}: emitter returned no keys -- enumeration is a no-op"
    base = _SOUNDS_DIR if subdir == "." else _SOUNDS_DIR / subdir
    bundled = {p.stem for p in base.glob("*.mp3")}
    assert registry == bundled, (
        f"{family}: TS registry keys != bundled stems\n"
        f"  registry-only (missing file): {sorted(registry - bundled)}\n"
        f"  disk-only (orphan asset):     {sorted(bundled - registry)}"
    )


def test_every_bundled_stem_is_generatable() -> None:
    """Every bundled stem, across all families, has a PROMPT regenerate recipe --

    ties registry -> bundled -> generatable into one chain. (The reverse
    orphan-PROMPT direction stays owned by test_generate_spell_sfx.py.)
    """
    prompts = _load_prompts()
    bundled = {p.stem for p in _SOUNDS_DIR.glob("**/*.mp3")}
    ungeneratable = sorted(bundled - set(prompts))
    assert not ungeneratable, f"bundled stems with no PROMPT regenerate recipe (not generatable): {ungeneratable}"


def test_no_uncompressed_wav_in_bundle() -> None:
    """No uncompressed .wav anywhere in the bundle (AC1, standalone E2E sanity)."""
    wavs = sorted(_SOUNDS_DIR.glob("**/*.wav"))
    assert not wavs, f"uncompressed .wav found in the bundle: {wavs}"
