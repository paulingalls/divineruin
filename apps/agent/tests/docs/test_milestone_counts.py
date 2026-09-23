"""Milestone totals and owner-backed claims must follow the shipped artifacts."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DOCS = ROOT / "docs/milestones"
BOX = re.compile(r"^- \[([ x])\] ", re.M)
ROW = re.compile(r"^\| (\d+) · [^|]+\| \[([^]]+\.md)\]\([^)]*\) \|[^|]*\| (\d+)/(\d+) ACs \|", re.M)


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_phase_and_overall_counts():
    readme = read("docs/milestones/README.md")
    rows = ROW.findall(readme)
    assert len(rows) == 13, "README needs exactly one count row per phase"
    assert {int(row[0]) for row in rows} == set(range(13))
    checked_sum = total_sum = 0
    for phase, filename, checked, total in rows:
        assert (
            filename
            == f"{int(phase):02d}_{['doc_updates', 'core_systems', 'archetypes', 'magic', 'combat', 'crafting', 'npcs', 'bestiary', 'patrons', 'economy', 'terrain', 'world_loop', 'story_content'][int(phase)]}.md"
        )
        boxes = BOX.findall((DOCS / filename).read_text())
        assert boxes, filename
        actual = (boxes.count("x"), len(boxes))
        assert actual == (int(checked), int(total)), (filename, actual, checked, total)
        checked_sum += int(checked)
        total_sum += int(total)
    position = re.search(r"\*\*Position: (\d+) / (\d+) acceptance criteria", read("docs/milestones/REMAINING.md"))
    assert position, "REMAINING needs a Position"
    assert (int(position[1]), int(position[2])) == (checked_sum, total_sum)


def test_m47_m48_evidence_paths():
    combat = read("docs/milestones/04_combat.md")
    for milestone in ("4.7", "4.8"):
        match = re.search(rf"^### Milestone {re.escape(milestone)}\b(.*?)(?=^### Milestone |\Z)", combat, re.M | re.S)
        assert match, milestone
        lines = [line for line in match[1].splitlines() if BOX.match(line)]
        assert lines, milestone
        for line in lines:
            assert line.startswith("- [x] "), line
            comment = re.search(r"<!-- verified (.*?) -->", line)
            assert comment, line
            paths = re.findall(r"apps/agent/tests/[\w/]+\.py", comment[1])
            assert paths, line
            assert all((ROOT / path).is_file() for path in paths), line


def test_patron_roster_matches_content():
    gods = json.loads(read("content/gods.json"))
    ids = [god["god_id"] for god in gods]
    assert ids and len(ids) == len(set(ids))
    claim = re.search(r"\*\*`content/gods\.json` has (\d+) of (\d+) patrons\*\*", read("docs/milestones/08_patrons.md"))
    assert claim, "Patron roster claim missing"
    assert (int(claim[1]), int(claim[2])) == (len(ids), len(ids))


def test_inner_fire_cost_matches_racial_content():
    racial = json.loads(read("content/racial_resonance_bonuses.json"))
    modifiers = next(row["modifiers"] for row in racial if row["id"] == "draethar")
    implementation = read("apps/agent/draethar_inner_fire.py")
    assert "inner_fire_resonance_reduction" in implementation
    assert "inner_fire_self_damage" in implementation
    magic = read("docs/milestones/03_magic.md")
    claim = re.search(
        r"^  - Draethar: Inner Fire — .*?−(\d+) Resonance \+ (\dd\d+) unpreventable self fire damage", magic, re.M
    )
    assert claim, "M3.4 Inner Fire cost claim missing"
    assert (int(claim[1]), claim[2]) == (
        modifiers["inner_fire_resonance_reduction"],
        modifiers["inner_fire_self_damage"],
    )


def test_veil_ward_scope_matches_migration():
    migration = read("scripts/migrations/057_veil_ward_scope.sql")
    assert "CREATE TABLE IF NOT EXISTS veil_wards" in migration
    assert "scope_kind  TEXT NOT NULL" in migration and "scope_id    TEXT NOT NULL" in migration
    assert "source      TEXT NOT NULL" in migration and "expires_at  TIMESTAMPTZ" in migration
    assert "CREATE INDEX IF NOT EXISTS idx_veil_wards_scope" in migration
    assert "UPDATE players SET data = data - 'veil_ward'" in migration
    for path in ("docs/milestones/03_magic.md", "docs/milestones/README.md"):
        doc = read(path)
        assert not re.search(r"per-player boolean", doc, re.I), path
        assert re.search(r"location/encounter-scoped, party-wide, duration-bound, multi-source", doc), path


def test_artificer_decision_is_fulfilled():
    adr = read("docs/decisions/0005-artificer-slot-deferred-to-phase-5.md")
    status = re.search(r"^Status: \*\*(.*?)\*\*", adr, re.M)
    assert status and status[1] == "Fulfilled"
