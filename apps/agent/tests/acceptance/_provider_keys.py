"""Conventions every provider-credential gate in this package shares.

They live apart from the gates that use them for a reason that is not taste:
`test_real_llm_key_guard.py` decides which scenarios must carry `pytest.mark.real_llm` by
walking test-side imports for the literal `ANTHROPIC_API_KEY`, so a gate for a DIFFERENT
provider that imported `_real_llm.py` for these two constants would make every one of its
scenarios declare itself an Anthropic scenario — and `bun run test:acceptance:nollm` would
then deselect a lane that never touches the LLM.
"""

from __future__ import annotations

# Set only on a human-approved paid run, beside ALLOW_PAID_TESTS (tests/_paid_tests.py):
# that run must reach real providers, so a tier that cannot fails loud rather than skipping.
OPT_IN_VAR = "REQUIRE_REAL_LLM"

# Every provider key in .env.example carries this prefix, and it is TRUTHY, so
# `skipif(not os.environ.get(...))` does not fire on it — a teammate worktree copies the
# file wholesale and would boot Docker before the provider refused the placeholder.
PLACEHOLDER_PREFIX = "your-"
