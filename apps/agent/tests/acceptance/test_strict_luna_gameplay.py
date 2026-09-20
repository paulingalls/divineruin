"""Seeded real-Luna gameplay matrix through LiveKit's tool binder."""

from __future__ import annotations

import json
import os

import pytest
from acceptance.strict_luna_fixtures import REQUIRED_CASE_IDS, load_case_manifest, run_luna_case
from acceptance.strict_luna_runtime import REPORT_PATH

pytestmark = pytest.mark.openai_real_llm

CASES = load_case_manifest()


@pytest.fixture(scope="module", autouse=True)
def _fresh_report() -> None:
    REPORT_PATH.write_text("")


@pytest.fixture(autouse=True)
def _luna_key_and_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or key.lower().startswith("your-"):
        pytest.fail("OPENAI_API_KEY is absent, empty, or a your-... placeholder")
    monkeypatch.setenv("GAMEPLAY_LLM", "openai-luna")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_seeded_luna_gameplay_case(case, reset_db_pool: str, record_property) -> None:
    report = await run_luna_case(case)
    record_property("strict_luna_case", report)
    assert report["passed"], report["diagnostic"]


def test_z_report_contains_every_executed_row() -> None:
    rows = [json.loads(line) for line in REPORT_PATH.read_text().splitlines() if line]
    assert len(rows) == 27
    assert {row["id"] for row in rows} == REQUIRED_CASE_IDS
    assert all(row["completion"] in {"completed", "failed"} for row in rows)
    assert all(row["request_count"] > 0 and row["input_tokens"] > 0 and row["output_tokens"] > 0 for row in rows)
    assert all(row["estimated_usd"] > 0 and row["price_source"] for row in rows)
