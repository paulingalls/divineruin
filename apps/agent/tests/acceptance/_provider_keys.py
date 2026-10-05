"""Shared opt-in and placeholder conventions for provider credentials."""

from __future__ import annotations

# Set only on a human-approved paid run, beside ALLOW_PAID_TESTS (tests/_paid_tests.py):
# that run must reach real providers, so a tier that cannot fails loud rather than skipping.
OPT_IN_VAR = "REQUIRE_REAL_LLM"

# Every provider key in .env.example carries this prefix, and it is TRUTHY, so
# `skipif(not os.environ.get(...))` does not fire on it — a teammate worktree copies the
# file wholesale and would boot Docker before the provider refused the placeholder.
PLACEHOLDER_PREFIX = "your-"
