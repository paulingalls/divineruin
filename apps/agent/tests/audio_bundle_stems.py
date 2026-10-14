"""Discover bundled stem sets for the compressed-audio product checks."""

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
