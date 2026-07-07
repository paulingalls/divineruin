"""Shared helper for the bundled-audio guard tests (not a test module itself).

Both test_audio_bundle_compressed.py and test_generate_spell_sfx.py discover the
bundled stem-set per family directory; this is the single implementation both
import (importable by name because apps/agent/tests is on the pytest pythonpath).
"""

from __future__ import annotations

from pathlib import Path


def bundled_stems_by_dir(sounds_dir: Path) -> dict[str, set[str]]:
    """Map each family dir (top-level '.' plus each subdir name) to its stem set."""
    families: dict[str, set[str]] = {}
    for path in sounds_dir.glob("**/*"):
        if path.suffix not in (".mp3", ".wav"):
            continue
        family = path.parent.relative_to(sounds_dir).as_posix()
        families.setdefault(family, set()).add(path.stem)
    return families
