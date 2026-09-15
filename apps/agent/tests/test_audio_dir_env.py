"""An empty ASYNC_AUDIO_DIR, as .env.example ships it, means unset: each reader keeps its default dir.

Each module reads the variable at import, so each case imports it in a fresh interpreter rather than
reloading a module other tests already hold.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = AGENT_DIR.parents[1] / "scripts"


def _audio_dir_after_import(module: str, import_root: Path) -> str:
    env = {**os.environ, "ASYNC_AUDIO_DIR": "", "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY") or "test-key"}
    code = f"import sys; sys.path.insert(0, {str(import_root)!r}); import {module}; print(repr({module}.AUDIO_DIR))"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=AGENT_DIR, env=env, capture_output=True, text=True, check=True
    )
    return ast.literal_eval(result.stdout.splitlines()[-1])


@pytest.mark.parametrize(
    ("module", "import_root", "default_suffix"),
    [
        ("llm_config", AGENT_DIR, "apps/server/audio"),
        ("prologue", AGENT_DIR, "assets/audio"),
        ("generate_prologue", SCRIPTS_DIR, "apps/server/audio"),
    ],
)
def test_an_empty_async_audio_dir_keeps_the_default_dir(module, import_root, default_suffix):
    audio_dir = _audio_dir_after_import(module, import_root)
    assert os.path.normpath(audio_dir).endswith(os.path.normpath(default_suffix))
