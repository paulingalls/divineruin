"""The milestone status table, the phase docs and the Position line must agree.

Three documents state the same numbers and nothing checked them, so sprint-046 shipped a
repo that called the L20 legendary companion both delivered (`02_archetypes.md`) and open
(`README.md`), with a Position line summing a table row that had already moved. That is
the failure REMAINING.md §7 calls structural: "phase-doc checkboxes drift from the code…
the gap is enforcement, not policy".

These read the docs, so they red on the doc that lies, whichever one it is.
"""

import re
from pathlib import Path

import pytest

_MILESTONES = Path(__file__).resolve().parents[3] / "docs" / "milestones"
_README = _MILESTONES / "README.md"
_REMAINING = _MILESTONES / "REMAINING.md"

_ROW = re.compile(
    r"^\| (?P<phase>\d+) · [^|]*\|\s*\[[^\]]+\]\((?P<doc>[^)]+)\)[^|]*\|[^|]*\|\s*"
    r"(?P<met>\d+)/(?P<total>\d+) ACs\s*\|",
    re.M,
)


def _rows() -> list[re.Match[str]]:
    rows = list(_ROW.finditer(_README.read_text()))
    assert len(rows) == 13, f"expected one row per phase doc, parsed {len(rows)}"
    return rows


def _doc_counts(doc: str) -> tuple[int, int]:
    text = (_MILESTONES / doc).read_text()
    met = len(re.findall(r"^- \[x\]", text, re.M))
    return met, met + len(re.findall(r"^- \[ \]", text, re.M))


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["doc"])
def test_readme_row_matches_its_phase_doc_checkboxes(row):
    assert _doc_counts(row["doc"]) == (int(row["met"]), int(row["total"]))


def test_remaining_position_is_the_sum_of_the_readme_table():
    rows = _rows()
    position = re.search(r"\*\*Position: ([\d,]+) / ([\d,]+) acceptance criteria", _REMAINING.read_text())
    assert position is not None, "REMAINING.md has no Position line"
    assert (int(position[1]), int(position[2])) == (
        sum(int(r["met"]) for r in rows),
        sum(int(r["total"]) for r in rows),
    )


def test_phase7_capstone_preserves_checked_scope_and_summary():
    text = (_MILESTONES / "07_bestiary.md").read_text()
    expected = {"7.1": (9, 0), "7.2": (11, 0), "7.3": (2, 8), "7.4": (0, 11)}
    sections = re.split(r"^### Milestone (7\.\d) —[^\n]+", text, flags=re.M)
    assert len(sections) == 9, "Phase 7 milestone corpus moved or emptied"
    for number, body in zip(sections[1::2], sections[2::2], strict=True):
        checked = re.findall(r"^- \[x\] (.*)", body, re.M)
        unchecked = re.findall(r"^- \[ \]", body, re.M)
        assert (len(checked), len(unchecked)) == expected[number]
        summary = re.search(rf"\| M{number} —[^|]+\| (\d+) \| (\d+) \| (\d+) \|", text)
        assert summary and tuple(map(int, summary.groups())) == (len(checked), 0, len(unchecked))
        if number == "7.3":
            assert all(
                line.startswith(("All 9 Hollow creatures", "Each Hollow creature has a distinct veil_effect"))
                for line in checked
            )


def test_phase7_capstone_names_cutover_refresh_and_deferred_mechanics():
    text = (_MILESTONES / "07_bestiary.md").read_text()
    for phrase in (
        "catalog references",
        "persisted snapshots",
        "agent snapshots",
        "committed HTTP",
        "authenticated GET /api/inventory",
        "open/resume",
        "five seconds",
        "foreground",
        "generation",
        "refresh error",
        "retry",
        "narrative-only",
        "command",
        "accusation",
        "restrictions",
        "terrain",
        "zone",
        "legendary",
        "Named",
        "deferred",
    ):
        assert phrase in text, f"Missing capstone contract: {phrase}"
    assert "The Still and Architect remain deferred Named encounters" in text
    assert (
        "Social `command` and `accusation` effects carry narrative-only focus/narration, without automatic healing or spell buff dice."
        in text
    )
    assert "story-136 owns" not in text.lower()
    spec = (_MILESTONES.parent / "game_mechanics/game_mechanics_bestiary.md").read_text()
    assert "Combat Effect Inventory" in spec
    assert "command social focus/narration; no automatic healing or spell buff dice" in spec
