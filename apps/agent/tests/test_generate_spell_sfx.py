"""Guard for the M17 spell-SFX generator's frozen prompt table (story-002).

The generator lives at scripts/audio/generate_spell_sfx.py — outside the agent
package — because it is a build-time asset tool, not agent runtime code. It is
imported here by file path so this guard runs in the collected `test:python`
lane (which roots at apps/agent/tests/), keeping the 7-key contract from
docs/audio_sfx_pipeline.md §4 under CI. Pure: importing the module defines the
prompt table with no network call (generation only happens in main()).
"""

import importlib.util
from pathlib import Path

# scripts/audio/generate_spell_sfx.py, relative to the repo root (three parents
# up from this test file: apps/agent/tests -> apps/agent -> apps -> repo root).
_GENERATOR_PATH = Path(__file__).resolve().parents[3] / "scripts" / "audio" / "generate_spell_sfx.py"

# The frozen source-by-effect palette — the contract stories 002 (asset filenames)
# and 003 (registry keys) both mirror. Must match docs/audio_sfx_pipeline.md §4.
FROZEN_KEYS = frozenset(
    {
        "spell_fire",
        "spell_ice",
        "spell_arcane_force",
        "spell_heal",
        "spell_radiant",
        "spell_nature",
        "spell_generic",
    }
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_spell_sfx", _GENERATOR_PATH)
    assert spec and spec.loader, f"cannot load generator at {_GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_file_exists():
    assert _GENERATOR_PATH.is_file(), f"missing generator: {_GENERATOR_PATH}"


def test_prompt_table_is_exactly_the_seven_frozen_keys():
    gen = _load_generator()
    assert set(gen.PROMPTS.keys()) == set(FROZEN_KEYS)


def test_every_prompt_is_a_nonempty_string():
    gen = _load_generator()
    for key, prompt in gen.PROMPTS.items():
        assert isinstance(prompt, str), f"{key} prompt is not a str"
        assert prompt.strip(), f"{key} prompt is empty"
