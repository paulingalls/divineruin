"""Opt-in hard gate for the real-LLM acceptance tier (sprint-47 story-019 AC1).

A tier that absents itself is a false green: the pre-push gate reported
`5 skipped` for an unknown span while the only scenarios that reach the Anthropic
API ran nowhere. Set REQUIRE_REAL_LLM=1 (the pre-push gate and `bun run
test:acceptance` both do) and a missing or placeholder key fails the lane loud.
"""

from __future__ import annotations

from collections.abc import Mapping

OPT_IN_VAR = "REQUIRE_REAL_LLM"
KEY_VAR = "ANTHROPIC_API_KEY"

# .env.example:7's value. It is truthy, so `skipif(not os.environ.get(...))` does not
# fire on it — every teammate worktree copies it and would 401 after booting Docker.
_PLACEHOLDER_PREFIX = "your-"


def require_real_llm_key(env: Mapping[str, str]) -> None:
    """Raise if the real-LLM tier is required but unusable. Silent when not opted in."""
    if not env.get(OPT_IN_VAR):
        return
    key = env.get(KEY_VAR, "")
    if not key:
        raise RuntimeError(
            f"{OPT_IN_VAR} is set but {KEY_VAR} is empty or absent: the real-LLM acceptance "
            f"scenarios would skip silently. Put a real key in .env, or unset {OPT_IN_VAR}."
        )
    if key.startswith(_PLACEHOLDER_PREFIX):
        raise RuntimeError(
            f"{KEY_VAR} is the .env.example placeholder {key!r}, not a real key — the real-LLM "
            f"scenarios would 401. Copy a real key into this checkout's .env, or unset {OPT_IN_VAR}."
        )
