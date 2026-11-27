import json
from datetime import datetime
from pathlib import Path

import pytest

from aethos_clock import aethos_day

ROOT = Path(__file__).resolve().parents[3]
CASES = json.loads((ROOT / "packages/shared/fixtures/aethos-day-cases.json").read_text())
CASE_IDS = [case["id"] for case in CASES]
assert CASE_IDS and len(CASE_IDS) == len(set(CASE_IDS))


@pytest.mark.parametrize("instant, expected", [(row["instant"], row["expected"]) for row in CASES], ids=CASE_IDS)
def test_aethos_day(instant: str, expected: int) -> None:
    assert aethos_day(datetime.fromisoformat(instant)) == expected
