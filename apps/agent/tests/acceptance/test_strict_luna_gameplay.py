"""Seeded real-Luna gameplay matrix through LiveKit's tool binder."""

from __future__ import annotations

import os

import pytest
from acceptance.strict_luna_fixtures import load_case_manifest, run_luna_case
from acceptance.strict_luna_runtime import REPORT_PATH

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY") and not os.environ.get("REQUIRE_REAL_LLM"),
        reason="Strict Luna acceptance requires OPENAI_API_KEY",
    ),
    pytest.mark.openai_real_llm,
]

CASES = load_case_manifest()


@pytest.fixture(scope="module", autouse=True)
def _fresh_report() -> None:
    REPORT_PATH.write_text("")


@pytest.fixture(autouse=True)
def _luna_key_and_default_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key.lower().startswith("your-"):
        if os.environ.get("REQUIRE_REAL_LLM"):
            pytest.fail("REQUIRE_REAL_LLM=1 but OPENAI_API_KEY is absent, empty, or a your-... placeholder")
        pytest.skip("Strict Luna acceptance requires OPENAI_API_KEY")
    monkeypatch.delenv("GAMEPLAY_LLM", raising=False)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_seeded_luna_gameplay_case(case, reset_db_pool: str, record_property) -> None:
    report = await run_luna_case(case)
    record_property("strict_luna_case", report)
    assert report["passed"], report["diagnostic"]
