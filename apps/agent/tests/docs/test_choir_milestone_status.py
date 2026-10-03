"""Delivered Choir mechanics do not certify the remaining Hollow or spell catalog effects."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
PATHS = (
    "docs/milestones/03_magic.md",
    "docs/milestones/07_bestiary.md",
    "docs/milestones/README.md",
    "docs/milestones/REMAINING.md",
    ".xp/config.yml",
    ".xp/constraints.md",
    ".xp/system.md",
    "docs/game_mechanics/game_mechanics_combat.md",
    "docs/game_mechanics/game_mechanics_magic.md",
    "docs/game_mechanics/game_mechanics_bestiary.md",
)
REMAINING = (
    "Corruption aura applies correctly based on distance and target saves",
    "`resolve_resonance_on_death` feeds correct Resonance deltas to nearby casters",
    "The Still has passive-until-attacked behavior with damage reflection",
    "The Architect has terrain manipulation abilities that alter combat grid state",
    "Tier 1-2 Hollow creatures function as standard combat encounters (no custom behavior needed)",
    "Tier 3 Hollowed Knight and Veilrender have boss-tier HP and multi-phase mechanics",
    "Tests cover corruption aura at various distances, resonance_on_death, and all 3 Tier 4 custom behaviors",
)


NATIVE_TODO = (
    "mus2471i-cbb68570",
    "experimental/incomplete",
    "normal capture",
    "fresh human go-ahead",
    "entry",
    "cast-aura",
    "aura-break",
    "search",
    "redirect",
    "silence",
    "refusal",
    "silenced-command",
    "interrupted",
    "deafened",
    "deafened-command",
    "expiry",
    "destruction",
    "replay",
    "new complete current-source sequence",
    "matched SFX deactivation fault",
    "identical settings",
    "dropped-gameplay",
    "bypassed-receiver",
    "skipped-encounter",
    "withheld-input",
    "DM-tone",
    "unrelated-burst",
)


def read_contract():
    return {path: (ROOT / path).read_text() for path in PATHS}


def assert_contract(texts):
    assert set(texts) == set(PATHS) and all(value.strip() for value in texts.values()), "empty status corpus"
    magic, bestiary, readme, remaining, config, constraints, system = (texts[path] for path in PATHS[:7])
    assert "M33 remains partial" in magic and "deferred spell effects" in magic
    assert "entire Magic system" not in magic and "Milestone-level status is **DELIVERED**" not in magic
    assert "M7.3 remains partial" in bestiary
    section = bestiary.split("### Milestone 7.3 —")[1].split("### Milestone 7.4 —")[0]
    assert all(f"- [ ] {criterion}" in section for criterion in REMAINING), "remaining Hollow criterion marked complete"
    assert "Choir Deafened and Still Charmed riders stay" not in bestiary
    assert "their custom runtime encounters remain deferred" not in bestiary
    assert "public combat query" in readme and "Still" in readme and "Architect" in readme
    assert "M33 remains partial" in remaining and "M7.3 remains partial" in remaining
    assert "TODO: complete native Choir audio acceptance" in remaining, "missing native TODO"
    for evidence in NATIVE_TODO:
        assert evidence in remaining, f"missing native TODO evidence: {evidence}"
    assert "Full native acceptance passed" not in remaining, "false native certification"
    for path in PATHS[7:9]:
        assert "preserve player microphone command transport" in texts[path], "rules disable player input"
        assert "apps/agent/tests/acceptance/test_choir_capstone.py" in texts[path], "rules omit focused evidence"
    assert "rejected interpretations" in texts[PATHS[9]], "inventory omits rejected effects"
    tests = yaml.safe_load(config)["tests"]
    assert tests["story"] == "bun run lint", "story tier must remain static"
    assert tests["full"] == "bash .githooks/pre-push __xp_full_tier__", "full routing changed"
    assert "the story tier runs static checks" in constraints and "Broad" in constraints
    assert "Story tier: `bun run lint` (static checks)" in system
    assert "separate concrete per-run human approval" in system
    assert "runs only at the comprehensive push or sprint-close boundary" not in system
    assert re.search(r"full tier once at sprint close", system)


def test_delivered_and_remaining_choir_status_and_testing_policy():
    assert_contract(read_contract())


@pytest.mark.parametrize("path", PATHS)
def test_missing_or_empty_status_corpus_fails(path):
    texts = read_contract()
    texts[path] = ""
    with pytest.raises(AssertionError, match="empty status corpus"):
        assert_contract(texts)


@pytest.mark.parametrize("criterion", REMAINING)
def test_each_remaining_hollow_criterion_cannot_be_checked(criterion):
    texts = read_contract()
    assert_contract(texts)
    path = PATHS[1]
    texts[path] = texts[path].replace(f"- [ ] {criterion}", f"- [x] {criterion}")
    with pytest.raises(AssertionError, match="remaining Hollow"):
        assert_contract(texts)


@pytest.mark.parametrize(
    "path,before,after",
    [
        (PATHS[0], "M33 remains partial", "M33 complete"),
        (PATHS[7], "preserve player microphone command transport", "disable all microphone transport"),
        (PATHS[8], "preserve player microphone command transport", "disable all microphone transport"),
        (PATHS[1], "M7.3 remains partial", "M7.3 complete"),
        (PATHS[3], "M33 remains partial", "M33 complete"),
        (PATHS[4], "story: bun run lint", "story: bun run test:all"),
        (PATHS[4], "full: bash .githooks/pre-push __xp_full_tier__", "full: bun run lint"),
        (PATHS[5], "the story tier runs static checks", "Story tier runs all tests"),
        (PATHS[6], "separate concrete per-run human approval", "blanket sprint approval"),
    ],
)
def test_status_and_policy_conflicts_are_rejected(path, before, after):
    texts = read_contract()
    assert_contract(texts)
    assert before in texts[path]
    texts[path] = texts[path].replace(before, after)
    with pytest.raises(AssertionError):
        assert_contract(texts)


@pytest.mark.parametrize("evidence", NATIVE_TODO)
def test_native_todo_cannot_omit_remaining_evidence(evidence):
    texts = read_contract()
    assert_contract(texts)
    texts[PATHS[3]] = texts[PATHS[3]].replace(evidence, "omitted")
    with pytest.raises(AssertionError, match="missing native TODO evidence"):
        assert_contract(texts)


def test_native_todo_cannot_certify_interrupted_run():
    texts = read_contract()
    assert_contract(texts)
    texts[PATHS[3]] += "\nFull native acceptance passed\n"
    with pytest.raises(AssertionError, match="false native certification"):
        assert_contract(texts)
