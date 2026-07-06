"""Guard for the generator's frozen + full-inventory prompt table (story-001).

The generator lives at scripts/audio/generate_spell_sfx.py — outside the agent
package — because it is a build-time asset tool, not agent runtime code. It is
imported here by file path so this guard runs in the collected `test:python`
lane (which roots at apps/agent/tests/), keeping both the frozen 7-key spell
contract and the full bundled-asset parity contract from
docs/audio_sfx_pipeline.md §4 under CI. Pure: importing the module defines the
prompt table with no network call (generation only happens in main()).
"""

import importlib.util
from pathlib import Path

# scripts/audio/generate_spell_sfx.py, relative to the repo root (three parents
# up from this test file: apps/agent/tests -> apps/agent -> apps -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GENERATOR_PATH = _REPO_ROOT / "scripts" / "audio" / "generate_spell_sfx.py"
_SOUNDS_DIR = _REPO_ROOT / "apps" / "mobile" / "assets" / "sounds"

# The frozen source-by-effect palette from the M17 capstone — the contract
# story-002 (asset filenames) and story-003 (registry keys) both mirror. Must
# match docs/audio_sfx_pipeline.md §4. Values are snapshotted below so this
# guard also catches accidental edits to the existing 7 prompts.
FROZEN_PROMPTS = {
    "spell_fire": (
        "Fantasy fire spell being cast and released. A soft inward whoosh as energy "
        "gathers, then a sharp ignition crack and a brief roar of expanding flame that "
        "fades to a dissipating crackle. Explosive magical release, not a sustained "
        "burn. Short, punchy game sound effect, dry, no music."
    ),
    "spell_ice": (
        "Fantasy ice spell being cast and released. A high glassy hiss as the air "
        "freezes, a sharp crystalline crack like rich shattering glass, then a brittle "
        "scatter of ice shards. High and bright, cold and precise. Short, punchy game "
        "sound effect, dry, no music."
    ),
    "spell_arcane_force": (
        "Fantasy arcane force spell being discharged. A low subsonic hum building "
        "rapidly in pitch, releasing as a concussive low-frequency thump felt in the "
        "chest, then a brief whoosh of displaced air. Heavy, low-mid, it pushes rather "
        "than crackles. Short, punchy game sound effect, dry, no music."
    ),
    "spell_heal": (
        "Fantasy healing spell activating. Soft and warm: a gentle rising tone like a "
        "quiet choir note from silence, releasing into a warm chime with a resonant "
        "shimmering tail. High-mid, no bass, kind and relieving. Short game sound "
        "effect, dry, no music."
    ),
    "spell_radiant": (
        "Fantasy divine radiant spell being cast, a smite of holy light. A warm "
        "ascending cathedral-like chime with a golden shimmer, releasing as a clean "
        "resonant burst of radiance. Authoritative and holy, not a heal. Short, punchy "
        "game sound effect, dry, no music."
    ),
    "spell_nature": (
        "Fantasy primal nature spell being cast. Sudden organic growth: rustling earth, "
        "cracking wood, and whipping vines and thorns erupting, with a green living "
        "texture. Earthy and alive. Short, punchy game sound effect, dry, no music."
    ),
    "spell_generic": (
        "A generic fantasy magic spell being cast. A neutral arcane shimmer and whoosh "
        "with a soft chime as energy gathers and releases, no specific element. Short "
        "game sound effect, dry, no music."
    ),
}
FROZEN_KEYS = frozenset(FROZEN_PROMPTS)

# Sting stems are idiomatically melodic musical flourishes, not dry SFX — exempt
# them from the "no music" style guard applied to the rest of the SFX/texture
# families. This is the one explicit list allowed; everything else derives from
# on-disk family directories so future assets auto-extend coverage.
STING_KEYS = frozenset(
    {
        "level_up_sting",
        "success_sting",
        "fail_sting",
        "quest_sting",
        "critical_hit_sting",
        "god_whisper_stinger",
    }
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_spell_sfx", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundled_stems_by_dir() -> dict[str, set[str]]:
    """Map each family dir (top-level '.' plus each subdir name) to its stem set."""
    families: dict[str, set[str]] = {}
    for path in _SOUNDS_DIR.glob("**/*"):
        if path.suffix not in (".mp3", ".wav"):
            continue
        family = path.parent.relative_to(_SOUNDS_DIR).as_posix()
        families.setdefault(family, set()).add(path.stem)
    return families


def test_generator_file_exists():
    assert _GENERATOR_PATH.is_file(), f"missing generator: {_GENERATOR_PATH}"


def test_seven_spell_keys_present_and_unchanged():
    gen = _load_generator()
    assert set(gen.PROMPTS.keys()) >= FROZEN_KEYS
    for key, prompt in FROZEN_PROMPTS.items():
        assert gen.PROMPTS[key] == prompt, f"{key} prompt changed from the frozen M17 value"


def test_every_prompt_is_a_nonempty_string():
    gen = _load_generator()
    for key, prompt in gen.PROMPTS.items():
        assert isinstance(prompt, str), f"{key} prompt is not a str"
        assert prompt.strip(), f"{key} prompt is empty"


def test_every_bundled_asset_stem_has_a_prompt():
    gen = _load_generator()
    all_stems = {stem for stems in _bundled_stems_by_dir().values() for stem in stems}
    missing = sorted(all_stems - set(gen.PROMPTS.keys()))
    assert not missing, f"bundled asset stems with no PROMPTS entry: {missing}"


def test_no_prompt_without_a_bundled_asset():
    gen = _load_generator()
    all_stems = {stem for stems in _bundled_stems_by_dir().values() for stem in stems}
    orphaned = sorted(set(gen.PROMPTS.keys()) - all_stems)
    assert not orphaned, f"PROMPTS keys with no bundled asset (typo or stale entry?): {orphaned}"


def test_sfx_family_prompts_are_dry():
    gen = _load_generator()
    families = _bundled_stems_by_dir()
    dry_families = {"."} | {d for d in families if d.startswith("textures")}
    dry_stems = {stem for family in dry_families for stem in families.get(family, set())}
    dry_stems -= STING_KEYS
    for key in sorted(dry_stems):
        prompt = gen.PROMPTS[key]
        assert "no music" in prompt.lower(), f"{key} is a dry SFX/texture prompt but lacks a 'no music' style guard"
