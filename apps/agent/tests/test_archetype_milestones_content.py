"""Content tests for content/archetype_milestones.json — the M2.3 milestone SSOT.

These read the raw JSON file directly (NOT a loader; the loader lives in
apps/agent/milestones.py, story-002). This module checks the JSON's structure:
roster coverage (every archetype has one row at each of L5/L10/L15/L20), the
tier<->level mapping, the L5 specialization-fork shape (exactly 2 options, or a
patron-deferred stub), the L10/L15/L20 auto-grant shape, and id well-formedness.
Mirrors test_archetype_abilities_content.py.

Schema (decision 4c0677dae1be — self-contained milestone records):
each record embeds its granted ability text directly; milestones do NOT FK into
archetype_abilities (which holds activatables only — these grants are passive
combat flags / markers consumed by story-004 and Phase-4 combat).

Spec-fidelity decisions (confirmed with customer):
- Oracle has a concrete L5 fork (Fateseer/Doomcaller, spec L870) — encoded fully.
  Only Cleric (4 patron domains) and Paladin (4 patron oaths) are patron-deferred
  stubs pending Phase 8 (risk 5ab73bf3720a).
- Extra Attack at L10 is assigned only to Warrior, Skirmisher, Paladin (assumption
  69d9cf96ac16) — not all martials; Guardian etc. get archetype-specific grants.
"""

import json
import re
from pathlib import Path

import pytest

MILESTONES_JSON = Path(__file__).resolve().parents[3] / "content" / "archetype_milestones.json"

# The 18 chassis ids (parity with content/archetypes.json roster).
ARCHETYPE_IDS = {
    "warrior",
    "guardian",
    "skirmisher",
    "mage",
    "artificer",
    "seeker",
    "druid",
    "beastcaller",
    "warden",
    "cleric",
    "paladin",
    "oracle",
    "rogue",
    "spy",
    "whisper",
    "bard",
    "diplomat",
    "marshal",
}

# Tier name <-> level. Identity is the L5 specialization fork; the rest auto-grant.
TIER_LEVEL = {"identity": 5, "power": 10, "mastery": 15, "legend": 20}

KINDS = {"specialization_fork", "auto_grant"}

# L5 forks shaped by a patron choice — stubbed (empty options) pending Phase 8.
PATRON_DEFERRED = {"cleric", "paladin"}

# Archetypes the spec grants Extra Attack at L10 (assumption 69d9cf96ac16).
EXTRA_ATTACK_L10 = {"warrior", "skirmisher", "paladin"}

REQUIRED_KEYS = {
    "id",
    "archetype_id",
    "tier",
    "level",
    "kind",
    "patron_deferred",
    "specialization_options",
    "grant",
    "narration_cue",
}

OPTION_KEYS = {"id", "name", "description"}
GRANT_KEYS = {"name", "effect", "flag"}

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    data = json.loads(MILESTONES_JSON.read_text())
    assert isinstance(data, list), "archetype_milestones.json must be a top-level array"
    by_id = {row["id"]: row for row in data}
    assert len(by_id) == len(data), "duplicate milestone id in archetype_milestones.json"
    return data


def _by_archetype(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {aid: [] for aid in ARCHETYPE_IDS}
    for row in rows:
        out.setdefault(row["archetype_id"], []).append(row)
    return out


def test_every_archetype_has_one_row_per_tier(rows):
    by_arch = _by_archetype(rows)
    for aid in ARCHETYPE_IDS:
        levels = sorted(r["level"] for r in by_arch[aid])
        assert levels == [5, 10, 15, 20], f"{aid} milestone levels {levels} != [5, 10, 15, 20]"
    # Exactly 18 archetypes x 4 tiers, no stray archetype_id.
    assert len(rows) == len(ARCHETYPE_IDS) * 4, f"expected {len(ARCHETYPE_IDS) * 4} milestone rows, found {len(rows)}"


def test_each_row_required_keys_and_enums(rows):
    for row in rows:
        rid = row.get("id", "<no id>")
        # Exact match, not superset — the row shape is the cross-language SSOT
        # contract for the story-002 (Python) and story-003 (TS) parsers.
        assert set(row) == REQUIRED_KEYS, (
            f"{rid} key mismatch: missing {REQUIRED_KEYS - set(row)}, extra {set(row) - REQUIRED_KEYS}"
        )
        assert row["archetype_id"] in ARCHETYPE_IDS, (
            f"{rid} archetype_id {row['archetype_id']!r} is not a known chassis id"
        )
        assert row["tier"] in TIER_LEVEL, f"{rid} tier {row['tier']!r} not in {sorted(TIER_LEVEL)}"
        assert TIER_LEVEL[row["tier"]] == row["level"], (
            f"{rid} tier {row['tier']!r} should be level {TIER_LEVEL[row['tier']]}, got {row['level']}"
        )
        assert row["kind"] in KINDS, f"{rid} kind {row['kind']!r} not in {sorted(KINDS)}"
        assert isinstance(row["patron_deferred"], bool), f"{rid} patron_deferred must be a bool"
        assert isinstance(row["narration_cue"], str) and row["narration_cue"], (
            f"{rid} narration_cue must be a non-empty string"
        )


def test_l5_is_specialization_fork(rows):
    l5 = {r["archetype_id"]: r for r in rows if r["level"] == 5}
    for aid in ARCHETYPE_IDS:
        row = l5[aid]
        rid = row["id"]
        assert row["kind"] == "specialization_fork", f"{rid} L5 must be a specialization_fork"
        assert row["grant"] is None, f"{rid} L5 fork must not carry a grant"
        opts = row["specialization_options"]
        if aid in PATRON_DEFERRED:
            assert row["patron_deferred"] is True, f"{rid} ({aid}) must be patron_deferred"
            assert opts == [], f"{rid} patron-deferred stub must have empty specialization_options"
        else:
            assert row["patron_deferred"] is False, f"{rid} ({aid}) must not be patron_deferred"
            assert len(opts) == 2, f"{rid} L5 fork must have exactly 2 options, found {len(opts)}"


def test_patron_deferred_set_is_exactly_cleric_and_paladin(rows):
    deferred = {r["archetype_id"] for r in rows if r["patron_deferred"]}
    assert deferred == PATRON_DEFERRED, f"patron_deferred archetypes {sorted(deferred)} != {sorted(PATRON_DEFERRED)}"


def test_specialization_option_shape(rows):
    for row in rows:
        for opt in row["specialization_options"]:
            oid = opt.get("id", "<no id>")
            assert set(opt) == OPTION_KEYS, (
                f"{row['id']} option {oid} key mismatch: "
                f"missing {OPTION_KEYS - set(opt)}, extra {set(opt) - OPTION_KEYS}"
            )
            assert isinstance(oid, str) and ID_RE.match(oid), f"malformed option id: {oid!r}"
            for k in ("name", "description"):
                assert isinstance(opt[k], str) and opt[k], f"{row['id']} option {oid} {k} must be a non-empty string"


def test_auto_grant_tiers(rows):
    for row in (r for r in rows if r["level"] in (10, 15, 20)):
        rid = row["id"]
        assert row["kind"] == "auto_grant", f"{rid} L{row['level']} must be kind auto_grant"
        assert row["patron_deferred"] is False, f"{rid} auto_grant must not be patron_deferred"
        assert row["specialization_options"] == [], f"{rid} auto_grant must have no options"
        grant = row["grant"]
        assert isinstance(grant, dict), f"{rid} auto_grant must carry a grant object"
        assert set(grant) == GRANT_KEYS, (
            f"{rid} grant key mismatch: missing {GRANT_KEYS - set(grant)}, extra {set(grant) - GRANT_KEYS}"
        )
        for k in ("name", "effect"):
            assert isinstance(grant[k], str) and grant[k], f"{rid} grant {k} must be a non-empty string"
        assert grant["flag"] is None or (isinstance(grant["flag"], str) and ID_RE.match(grant["flag"])), (
            f"{rid} grant.flag must be null or a snake_case string"
        )


def test_l10_extra_attack_flag(rows):
    l10 = {r["archetype_id"]: r for r in rows if r["level"] == 10}
    for aid in EXTRA_ATTACK_L10:
        flag = l10[aid]["grant"]["flag"]
        assert flag == "extra_attack", f"{aid} L10 grant.flag {flag!r} should be 'extra_attack' per spec"
    # No other archetype's L10 should claim the extra_attack flag.
    for aid, row in l10.items():
        if aid not in EXTRA_ATTACK_L10:
            assert row["grant"]["flag"] != "extra_attack", (
                f"{aid} L10 must not carry the extra_attack flag (spec assigns it elsewhere)"
            )


def test_ids_unique_and_well_formed(rows):
    for row in rows:
        rid = row["id"]
        assert isinstance(rid, str) and ID_RE.match(rid), f"malformed milestone id: {rid!r}"
