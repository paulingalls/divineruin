"""Arms the live-voice credential gate for every scenario in this package.

The modules' own `skipif` handles the not-opted-in run; this is the other half — when a
human-approved paid run (ALLOW_PAID_TESTS=1 with REQUIRE_REAL_LLM=1) meets a missing or
placeholder key, the lane fails loud instead of
reporting a green that reached no microphone. Same shape as the `real_llm` fixture in the
parent conftest.
"""

from __future__ import annotations

import os

import pytest
from acceptance._live_voice import require_live_voice_key


@pytest.fixture(autouse=True)
def _live_voice_key_required() -> None:
    try:
        require_live_voice_key(os.environ)
    except RuntimeError as exc:
        pytest.fail(str(exc))
