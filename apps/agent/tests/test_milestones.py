"""Tests for milestones.py — the DB-loaded archetype-milestone content config (M2.3).

Mirrors the abilities.py loader contract: parse_milestone_row (fail-loud, shared
by the DB loader and the JSON test fixture), set_milestones (test seam),
get_milestone / get_archetype_milestones (accessors), is_loaded, and the
build-then-swap load_milestones (a malformed row must not wipe an already-loaded
map). The row shape is the self-contained milestone record (decision 4c0677dae1be,
story-001): id, archetype_id, tier, level, kind, patron_deferred,
specialization_options[], grant{name,effect,flag}|null, narration_cue.

The conftest autouse seed_milestones fixture pre-populates the map from content
before each test, but every test here seeds its own state up front
(set_milestones / a JSON helper) and so is verifiable independent of that fixture:
test_is_loaded_reflects_population deliberately clears the pre-seeded map with
set_milestones({}) to assert the empty case.
"""

import json
from pathlib import Path

import pytest

from milestones import (
    Grant,
    Milestone,
    SpecializationOption,
    get_archetype_milestones,
    get_milestone,
    is_loaded,
    load_milestones,
    parse_milestone_row,
    set_milestones,
)

CONTENT_PATH = Path(__file__).resolve().parents[3] / "content" / "archetype_milestones.json"

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

_FORK_ROW = {
    "id": "warrior_identity",
    "archetype_id": "warrior",
    "tier": "identity",
    "level": 5,
    "kind": "specialization_fork",
    "patron_deferred": False,
    "specialization_options": [
        {"id": "warrior_battle_master", "name": "Battle Master", "description": "Tactical maneuvers."},
        {"id": "warrior_berserker", "name": "Berserker", "description": "Rage state."},
    ],
    "grant": None,
    "narration_cue": "Two roads diverge before you, warrior.",
}

_GRANT_ROW = {
    "id": "warrior_power",
    "archetype_id": "warrior",
    "tier": "power",
    "level": 10,
    "kind": "auto_grant",
    "patron_deferred": False,
    "specialization_options": [],
    "grant": {"name": "Extra Attack", "effect": "Make 2 attacks per round instead of 1.", "flag": "extra_attack"},
    "narration_cue": "Your blade strikes twice where once it struck once.",
}

_DEFERRED_ROW = {
    "id": "cleric_identity",
    "archetype_id": "cleric",
    "tier": "identity",
    "level": 5,
    "kind": "specialization_fork",
    "patron_deferred": True,
    "specialization_options": [],
    "grant": None,
    "narration_cue": "Your domain is shaped by your patron.",
}


def _seed_from_content() -> None:
    raw = json.loads(CONTENT_PATH.read_text())
    set_milestones({row["id"]: parse_milestone_row(row["id"], row) for row in raw})


# --- parse_milestone_row -------------------------------------------------------


def test_parse_milestone_row_fork_shape():
    m = parse_milestone_row(_FORK_ROW["id"], _FORK_ROW)
    assert isinstance(m, Milestone)
    assert (m.id, m.archetype_id, m.tier, m.level) == ("warrior_identity", "warrior", "identity", 5)
    assert m.kind == "specialization_fork"
    assert m.patron_deferred is False
    assert m.grant is None
    assert len(m.specialization_options) == 2
    assert all(isinstance(o, SpecializationOption) for o in m.specialization_options)
    assert m.specialization_options[0] == SpecializationOption(
        id="warrior_battle_master", name="Battle Master", description="Tactical maneuvers."
    )


def test_parse_milestone_row_auto_grant_shape():
    m = parse_milestone_row(_GRANT_ROW["id"], _GRANT_ROW)
    assert m.kind == "auto_grant"
    assert m.specialization_options == ()
    assert m.grant == Grant(name="Extra Attack", effect="Make 2 attacks per round instead of 1.", flag="extra_attack")


def test_parse_milestone_row_deferred_stub_has_no_options_or_grant():
    m = parse_milestone_row(_DEFERRED_ROW["id"], _DEFERRED_ROW)
    assert m.patron_deferred is True
    assert m.specialization_options == ()
    assert m.grant is None


def test_parse_milestone_row_fail_loud_names_the_row():
    bad = {k: v for k, v in _GRANT_ROW.items() if k != "grant"}
    with pytest.raises(ValueError, match="warrior_power"):
        parse_milestone_row("warrior_power", bad)


def test_parse_milestone_row_rejects_unknown_tier():
    bad = {**_GRANT_ROW, "tier": "ascension"}
    with pytest.raises(ValueError, match=r"tier"):
        parse_milestone_row(_GRANT_ROW["id"], bad)


def test_parse_milestone_row_rejects_unknown_kind():
    bad = {**_GRANT_ROW, "kind": "passive_grant"}
    with pytest.raises(ValueError, match=r"kind"):
        parse_milestone_row(_GRANT_ROW["id"], bad)


def test_parse_milestone_row_rejects_noninteger_level():
    bad = {**_GRANT_ROW, "level": "10"}
    with pytest.raises(ValueError, match=r"level"):
        parse_milestone_row(_GRANT_ROW["id"], bad)


def test_parse_milestone_row_rejects_malformed_grant_missing_key():
    bad = {**_GRANT_ROW, "grant": {"name": "X", "flag": None}}
    with pytest.raises(ValueError, match="warrior_power"):
        parse_milestone_row("warrior_power", bad)


def test_parse_milestone_row_rejects_malformed_option_missing_key():
    bad = {**_FORK_ROW, "specialization_options": [{"id": "x", "name": "X"}]}
    with pytest.raises(ValueError, match="warrior_identity"):
        parse_milestone_row("warrior_identity", bad)


# --- accessors -----------------------------------------------------------------


def test_get_archetype_milestones_returns_four_tiers():
    _seed_from_content()
    warrior = get_archetype_milestones("warrior")
    assert sorted(m.level for m in warrior) == [5, 10, 15, 20]
    assert all(m.archetype_id == "warrior" for m in warrior)


def test_get_archetype_milestones_resolves_all_18():
    _seed_from_content()
    for aid in ARCHETYPE_IDS:
        ms = get_archetype_milestones(aid)
        assert sorted(m.level for m in ms) == [5, 10, 15, 20], f"{aid} missing a tier"


def test_get_archetype_milestones_unknown_returns_empty():
    set_milestones({"warrior_identity": parse_milestone_row(_FORK_ROW["id"], _FORK_ROW)})
    assert get_archetype_milestones("nope") == ()


def test_l5_fork_and_deferred_invariants_via_content():
    _seed_from_content()
    warrior_l5 = next(m for m in get_archetype_milestones("warrior") if m.level == 5)
    assert warrior_l5.kind == "specialization_fork" and len(warrior_l5.specialization_options) == 2
    cleric_l5 = next(m for m in get_archetype_milestones("cleric") if m.level == 5)
    assert cleric_l5.patron_deferred is True and cleric_l5.specialization_options == ()
    # Oracle is NOT patron-deferred (concrete fork per decision m23-l5-fork-spec-fidelity).
    oracle_l5 = next(m for m in get_archetype_milestones("oracle") if m.level == 5)
    assert oracle_l5.patron_deferred is False and len(oracle_l5.specialization_options) == 2


def test_get_milestone_resolves_and_unknown_raises():
    set_milestones({"warrior_power": parse_milestone_row(_GRANT_ROW["id"], _GRANT_ROW)})
    grant = get_milestone("warrior_power").grant
    assert grant is not None and grant.flag == "extra_attack"
    with pytest.raises(ValueError, match="nope"):
        get_milestone("nope")


def test_set_milestones_seam_replaces_state():
    set_milestones({"warrior_identity": parse_milestone_row(_FORK_ROW["id"], _FORK_ROW)})
    assert get_milestone("warrior_identity").tier == "identity"
    with pytest.raises(ValueError):
        get_milestone("warrior_power")


def test_is_loaded_reflects_population():
    set_milestones({})
    assert is_loaded() is False
    set_milestones({"warrior_identity": parse_milestone_row(_FORK_ROW["id"], _FORK_ROW)})
    assert is_loaded() is True


# --- build-then-swap load_milestones (DB path) ---------------------------------


class _FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


async def test_load_milestones_malformed_row_does_not_wipe_loaded_map(monkeypatch):
    set_milestones({"warrior_power": parse_milestone_row(_GRANT_ROW["id"], _GRANT_ROW)})

    import db

    bad_rows = [
        {"id": _FORK_ROW["id"], "data": json.dumps(_FORK_ROW)},
        {"id": "broken", "data": json.dumps({**_GRANT_ROW, "id": "broken", "kind": "passive_grant"})},
    ]

    async def fake_get_pool():
        return _FakePool(bad_rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    with pytest.raises(ValueError):
        await load_milestones()

    # Prior map survived the failed load.
    surviving = get_milestone("warrior_power").grant
    assert surviving is not None and surviving.name == "Extra Attack"
    # Build-then-swap: the well-formed row preceding the malformed one must NOT have
    # leaked into the live map (an inline-mutate load would have leaked it).
    with pytest.raises(ValueError, match="warrior_identity"):
        get_milestone("warrior_identity")


async def test_load_milestones_populates_from_pool(monkeypatch):
    set_milestones({})
    import db

    rows = [
        {"id": _FORK_ROW["id"], "data": json.dumps(_FORK_ROW)},
        {"id": _GRANT_ROW["id"], "data": _GRANT_ROW},  # dict (asyncpg may return parsed JSONB)
    ]

    async def fake_get_pool():
        return _FakePool(rows)

    monkeypatch.setattr(db, "get_pool", fake_get_pool)

    await load_milestones()
    assert is_loaded() is True
    assert len(get_milestone("warrior_identity").specialization_options) == 2
    grant = get_milestone("warrior_power").grant
    assert grant is not None and grant.flag == "extra_attack"
