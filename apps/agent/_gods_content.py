"""Shared loader for content/gods.json — sole chokepoint per ADR 0001.

Callers should read patron data via load_gods(); pinning tests in a follow-up
commit enforce this by construction.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

_GODS_JSON_PATH = Path(__file__).resolve().parents[2] / "content" / "gods.json"


@functools.cache
def load_gods() -> list[dict]:
    """Return the raw gods.json entries. Cached per process — do not mutate."""
    return json.loads(_GODS_JSON_PATH.read_text())
