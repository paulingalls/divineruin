"""AC7: the companion_kael literal stays deleted.

WALKS `git ls-files`, NOT rglob. rglob does not honour .gitignore, and a working checkout that
has run the agent, the test lane or the pre-push gate carries Kael in apps/agent/transcripts/,
flake-artifacts/ and apps/agent/.pytest_cache/v/cache/nodeids — an rglob walker reds on those
machines and nowhere else. rglob("*") + read_text() also raises UnicodeDecodeError on
assets/images/companion_kael_primary.png, whose PATH matches the pattern. Tracked files are
exactly the set story-013's inventory reasoned about.

CASE-SENSITIVE. .env.example:19 carries INWORLD_VOICE_KAEL and story-014 adds 19 more
INWORLD_VOICE_* lines, so a case-insensitive walk reds on whichever of the two cards lands
second.

COMPANION_KAEL IS MATCHED EXPLICITLY, beyond the card's prescribed pattern. Case-sensitively
neither `companion_kael` nor `\\bKael\\b` matches the ventriloquism voice tag — and a surviving
tag in a prompt is precisely what sprint-046 shipped to review round 2 (constraint 8). Cost of
the third alternative: two files that would otherwise not be listed, voices.py and
activity_templates.py, both legitimately companion-complete and allowlisted as such.
INWORLD_VOICE_KAEL contains KAEL but not COMPANION_KAEL, so .env.example stays clean.

TEST FILES ARE EXCLUDED BY PATH, and the exclusion is load-bearing. The same pattern matches
most of the companion suites, nearly all of them legitimately exercising Kael's row, because
Kael is a real companion and always will be. Tests ARE production code (constraint 2) and the
four test-side literals that mattered are pinned individually by their own suites; a repo walk
cannot tell those from the legitimate ones, so it does not try. Decide by PATH, not filename:
apps/mobile/src/__tests__/use-game-events.helpers.ts carries a player fixture named Kael and
no test marker in its filename.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

PATTERN = re.compile(r"companion_kael|COMPANION_KAEL|\bKael\b")
NEGATIVE = re.compile(r"Kaelen|Kaelthos")
SKIP_DIRS = (".venv", "node_modules", ".git", ".xp", "docs", "playtest", "dist", ".expo")
TEST_PATH_MARKERS = ("/tests/", "/__tests__/", ".test.", "_test.", ".feature")
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".mp3", ".wav", ".ico", ".ttf", ".otf"}

ALLOWLIST = {
    # story-020 owns every authored line about a companion (human decision 2026-09-04).
    "apps/agent/onboarding_prompt.py": "beat-3/4 vignettes — story-020",
    "apps/server/src/catchup.ts": "catch-up chatter — story-020",
    # Kael-only portrait ASSETS: four companions need four asset sets (art task, debt 9f6a7ada).
    "apps/agent/db.py": "Kael is the only companion with generated portrait assets",
    "scripts/generate_art.ts": "the asset generator for the above",
    # Kael's own rows.
    "content/companions.json": "Kael's companion row",
    "content/voice_registry.json": "Kael's voice row",
    "apps/agent/voices.py": "VOICES registry — all four companions",
    "apps/agent/activity_templates.py": "companion errand personas — all four companions",
    # Comments/docstrings naming Kael as one example among four.
    "apps/agent/async_rules.py": "comment recording that the Kael default was removed",
    "apps/agent/catalog_parse.py": "docstring example",
    "apps/agent/companion_profiles.py": "docstring examples",
    "apps/agent/companion_relationship_queries.py": "docstring example",
    "apps/agent/companion_scaling.py": "docstring example",
    "apps/agent/errand_resolution.py": "docstring naming the defect it fixed",
    "apps/agent/errand_tools.py": "docstring example",
    "packages/shared/src/entities/companion.ts": "comments + an id-format example",
    # "Kael" as a PLAYER character, not the companion — renaming is a different change.
    "apps/server/src/debug.ts": "debug-page fixture player",
    "content/players.json": "seed player",
    # Applied migration — immutable, never edit.
    "scripts/migrations/042_companions.sql": "comment in an applied migration",
}


def _is_test_path(path: str) -> bool:
    return any(marker in f"/{path}" for marker in TEST_PATH_MARKERS)


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def _matching_non_test_paths() -> set[str]:
    hits: set[str] = set()
    for path in _tracked_files():
        if any(path.startswith(f"{d}/") or f"/{d}/" in path for d in SKIP_DIRS):
            continue
        if _is_test_path(path) or Path(path).suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if PATTERN.search(NEGATIVE.sub("", text)):
            hits.add(path)
    return hits


def test_the_walk_is_not_vacuous():
    """The guard is a set difference; if the walk finds nothing it certifies nothing
    (constraint 1). Every allowlisted path is a known hit, so the walk must find at least them."""
    assert len(_matching_non_test_paths()) >= len(ALLOWLIST)


def test_only_allowlisted_non_test_files_name_kael():
    unexpected = sorted(_matching_non_test_paths() - set(ALLOWLIST))
    assert not unexpected, (
        "companion_kael / COMPANION_KAEL / Kael reappeared outside the allowlist: "
        f"{unexpected}. Resolve the companion from the player's archetype "
        "(companion_profiles.select_companion_for_archetype), or add the path to ALLOWLIST "
        "with the reason it is legitimately Kael-specific."
    )


def test_the_allowlist_has_not_rotted():
    """A stale entry silently widens the allowlist, and a stale entry is how the next card
    re-pads this one."""
    matching = _matching_non_test_paths()
    stale = sorted(path for path in ALLOWLIST if path not in matching)
    assert not stale, f"ALLOWLIST entries that no longer match — delete them: {stale}"
