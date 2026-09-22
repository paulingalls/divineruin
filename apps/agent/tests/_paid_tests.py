"""Tests that spend money on a provider never run without explicit human approval.

Human decision 2026-09-22: paid tests are skipped everywhere — pre-push, the sprint full
tier, CI, ad-hoc runs — even when provider keys are present. They run case by case, only
when a human approves that run, by setting ALLOW_PAID_TESTS=1 on that one invocation.
Key presence is NOT approval: every checkout's .env carries real keys.

REQUIRE_REAL_LLM keeps its narrower meaning inside an approved run: a missing or
placeholder key fails loud instead of skipping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

APPROVAL_VAR = "ALLOW_PAID_TESTS"
PAID_MARKERS = frozenset({"real_llm", "openai_real_llm", "live_voice"})


def paid_skip_reason(marker_names: Iterable[str], env: Mapping[str, str]) -> str | None:
    """The skip reason for an unapproved paid test, or None when the test may run."""
    paid = PAID_MARKERS.intersection(marker_names)
    if not paid or env.get(APPROVAL_VAR) == "1":
        return None
    return (
        f"paid provider test ({', '.join(sorted(paid))}) skipped: set {APPROVAL_VAR}=1 on a "
        "single invocation only with explicit human approval"
    )
