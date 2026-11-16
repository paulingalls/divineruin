"""Prologue authoring stays in the bundle, independent of generated media."""

import os
import subprocess
import sys
from pathlib import Path


def test_prologue_generator_writes_the_bundled_destination(tmp_path):
    root = Path(__file__).resolve().parents[3]
    env = dict(os.environ, MEDIA_DIR=str(tmp_path / "generated"), ASYNC_AUDIO_DIR=str(tmp_path / "retired"))
    result = subprocess.run(
        [sys.executable, "-c", "import generate_prologue; print(generate_prologue.AUDIO_DIR)"],
        cwd=root / "scripts",
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(root / "assets/audio")
