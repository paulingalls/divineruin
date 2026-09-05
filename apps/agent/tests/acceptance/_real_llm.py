"""Opt-in hard gate for the real-LLM acceptance tier (sprint-47 story-019 AC1).

A tier that absents itself is a false green: the pre-push gate reported
`5 skipped` for an unknown span while the only scenarios that reach the Anthropic
API ran nowhere. Set REQUIRE_REAL_LLM=1 (the pre-push gate and `bun run
test:acceptance` both do) and a missing or placeholder key fails the lane loud.

The CAUSE of those skips, measured 2026-09-05: `bun run <script>` does NOT put `.env`
into the environment of the command it spawns (bun 1.3.14 — it loads `.env` for
JavaScript it executes, not for a package script's shell child), so pytest never saw
the key that `.env` has carried all along. That is why `test:acceptance` passes
`uv run --env-file ../../.env`. The flag reads as redundant and is not: drop it and
this gate reds on every run. Precedence checked too — `--env-file` does not override
an already-exported variable, so a real key in the shell still wins over a worktree
`.env` carrying the placeholder.
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
