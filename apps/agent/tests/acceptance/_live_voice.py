"""Credential gate for the live-voice acceptance lane.

Marked microphone scenarios drive the REAL Deepgram STT API, and
without a usable key each one dies inside session setup with a vendor error that names no
cause. REJECTED: branching the CI step on the secret and passing
`--ignore=tests/acceptance/multiplayer_voice` when it is absent. That gates one invocation
and keys on a directory path, so an ad-hoc `uv run pytest tests/`,
`bun run test:acceptance:nollm`, a later job, or a voice scenario added elsewhere all meet
the nameless failure again.

So the gate is the one `_real_llm.py` establishes for the Anthropic tier and it lives with
the tests: `skipif` for runs that did not ask for real providers, a LOUD failure for the
runs that did. The opt-in flag is the shared `OPT_IN_VAR` rather than a live-voice flag of
its own, because a second flag would have to be threaded through the same hook and package
scripts to mean what that one already means at both boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping

from acceptance._provider_keys import OPT_IN_VAR, PLACEHOLDER_PREFIX

KEY_VAR = "DEEPGRAM_API_KEY"


def has_live_voice_key(env: Mapping[str, str]) -> bool:
    """Is there a key the Deepgram API would accept? The placeholder is truthy and is not one."""
    key = env.get(KEY_VAR, "")
    return bool(key) and not key.startswith(PLACEHOLDER_PREFIX)


def require_live_voice_key(env: Mapping[str, str]) -> None:
    """Raise if the live-voice tier is required but unusable. Silent when not opted in."""
    if not env.get(OPT_IN_VAR):
        return
    key = env.get(KEY_VAR, "")
    if not key:
        raise RuntimeError(
            f"{OPT_IN_VAR} is set but {KEY_VAR} is empty or absent: the live-voice acceptance "
            f"scenarios would skip silently. Put a real key in .env, or unset {OPT_IN_VAR}."
        )
    if key.startswith(PLACEHOLDER_PREFIX):
        raise RuntimeError(
            f"{KEY_VAR} is the .env.example placeholder {key!r}, not a real key — the live-voice "
            f"scenarios would fail in STT setup. Copy a real key into this checkout's .env, "
            f"or unset {OPT_IN_VAR}."
        )
