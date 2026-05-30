"""Verifies the operator-reset procedure in docs/ops/async-activity-reset.md.

revert_claim preserves the cached outcome/narration for the TTS-retry fast path,
so a poisoned cache loops forever (concern cc6195d3cc87). The runbook documents
the SQL an operator runs to clear that cache and force a clean re-resolution.
This test extracts the EXACT reset block from the runbook and runs it against a
real testcontainer row, so the documented procedure can't silently rot — editing
the runbook's SQL re-runs here. Runs under REQUIRE_DOCKER; skips when Docker down.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from acceptance.seeds import seed_player

import db

_RUNBOOK = Path(__file__).parents[4] / "docs" / "ops" / "async-activity-reset.md"

# Fields revert_claim/the worker cache onto a row that a reset must clear so the
# next tick re-resolves cleanly instead of replaying the poisoned cache.
_CACHE_FIELDS = (
    "outcome",
    "narration_text",
    "narration_summary",
    "narration_segments",
    "decision_options",
    "resolve_attempts",
    "resolving_at",
)


def _runbook_reset_sql() -> str:
    """Extract the single reset UPDATE from the runbook's ```sql fences."""
    text = _RUNBOOK.read_text()
    blocks = re.findall(r"```sql\n(.*?)```", text, re.DOTALL)
    resets = [b for b in blocks if "UPDATE async_activities" in b and "in_progress" in b]
    assert len(resets) == 1, f"expected exactly one reset UPDATE block in {_RUNBOOK.name}, found {len(resets)}"
    return resets[0].strip()


# The two states an operator finds a stuck activity in:
#   - "resolving" + resolving_at: a worker crashed mid-claim (recovered by the
#     stale sweep, but its cache may be poisoned).
#   - "in_progress" without resolving_at, resolve_attempts past the threshold: the
#     warned retry loop — revert_claim left it in_progress and stripped resolving_at.
# The reset must work on both; JSONB key-strip is a no-op on an already-absent key.
@pytest.mark.parametrize(
    "status,include_resolving_at",
    [("resolving", True), ("in_progress", False)],
    ids=["mid-claim-resolving", "warned-loop-in-progress"],
)
async def test_runbook_reset_clears_poisoned_cache(reset_db_pool: str, status: str, include_resolving_at: bool) -> None:
    pool = await db.get_pool()
    await seed_player(pool, player_id="player_stuck")
    activity_id = "activity_stuck"
    poisoned = {
        "status": status,
        "activity_type": "crafting",
        "resolve_attempts": 7,
        "outcome": {"tier": "failure"},
        "narration_text": "poisoned",
        "narration_summary": "poisoned",
        "narration_segments": [{"character": "X", "emotion": "flat", "text": "z"}],
        "decision_options": [],
        "parameters": {"recipe_id": "wooden_club"},
    }
    if include_resolving_at:
        poisoned["resolving_at"] = "2026-01-01T00:00:00+00:00"
    await pool.execute(
        "INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET data = $3::jsonb",
        activity_id,
        "player_stuck",
        json.dumps(poisoned),
    )

    # Run the documented reset verbatim ($1 = the stuck activity id).
    await pool.execute(_runbook_reset_sql(), activity_id)

    row = await pool.fetchrow("SELECT data FROM async_activities WHERE id = $1", activity_id)
    data = json.loads(row["data"])
    assert data["status"] == "in_progress"
    for field in _CACHE_FIELDS:
        assert field not in data, f"reset did not clear cached field {field!r}"
    # The parameters needed to re-resolve must survive the reset.
    assert data["parameters"]["recipe_id"] == "wooden_club"
