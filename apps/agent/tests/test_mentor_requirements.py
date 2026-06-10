"""Unit tests for mentor_requirements (sprint-011 / story-002).

check_mentor_requirements reads a mentor's mentor{} training block (story-001) and
gates the player on disposition/quest/gold/skill against injectable db seams. Pure
read-only logic — every seam is an AsyncMock here, so no DB is touched. pytest runs
in asyncio AUTO mode, so async tests need no marker.
"""

import json
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

import mentor_requirements as mr

_CONTENT = Path(__file__).resolve().parents[3] / "content"

# A mentor binding whose every gate a default player clears.
_REQS_OPEN = {"disposition": "neutral", "quest": None, "gold": 0, "skill": None}


def _queries(**overrides):
    """db_queries seam with permissive defaults; override per test."""
    m = Mock()
    m.get_player = AsyncMock(return_value={"gold": 1000})
    m.get_player_quest = AsyncMock(return_value=None)
    m.get_skill_advancement = AsyncMock(return_value={})
    for key, value in overrides.items():
        setattr(m, key, value)
    return m


def _content(npc):
    m = Mock()
    m.get_npc = AsyncMock(return_value=npc)
    return m


def _variants(mentor_id="mentor_x"):
    m = Mock()
    m.get_mentor_variant = Mock(return_value=types.SimpleNamespace(id="v1", mentor_id=mentor_id, ability_id="a1"))
    return m


def _disposition(value):
    m = Mock()
    m.resolve_disposition = AsyncMock(return_value=value)
    return m


def _npc(requirements, mentor_id="mentor_x"):
    return {"id": mentor_id, "mentor": {"culture": "X", "training_cycles": 3, "requirements": requirements}}


async def _check(reqs, *, mentor_id="mentor_x", variant_mentor="mentor_x", disposition="trusted", **queries):
    return await mr.check_mentor_requirements(
        "p1",
        mentor_id,
        "v1",
        queries_mod=_queries(**queries),
        content_mod=_content(_npc(reqs, mentor_id)),
        variants_mod=_variants(variant_mentor),
        disposition_mod=_disposition(disposition),
    )


# --- aggregate: met / unmet -------------------------------------------------


async def test_all_requirements_met():
    reqs = {"disposition": "friendly", "quest": None, "gold": 50, "skill": "Athletics: Trained"}
    res = await _check(
        reqs,
        disposition="trusted",
        get_player=AsyncMock(return_value={"gold": 100}),
        get_skill_advancement=AsyncMock(return_value={"athletics": {"tier": "expert"}}),
    )
    assert res.met is True
    assert res.unmet == []


async def test_disposition_below_and_quest_missing_lists_both():
    reqs = {"disposition": "trusted", "quest": "thornwatch_patrol", "gold": 0, "skill": None}
    res = await _check(
        reqs,
        disposition="neutral",
        get_player_quest=AsyncMock(return_value={"status": "active"}),
    )
    assert res.met is False
    assert len(res.unmet) == 2
    joined = " ".join(res.unmet)
    assert "disposition" in joined and "trusted" in joined and "neutral" in joined
    assert "quest" in joined and "thornwatch_patrol" in joined


@pytest.mark.parametrize("gold,met", [(49, False), (50, True), (51, True)])
async def test_gold_boundary(gold, met):
    reqs = {"disposition": "neutral", "quest": None, "gold": 50, "skill": None}
    res = await _check(reqs, disposition="neutral", get_player=AsyncMock(return_value={"gold": gold}))
    assert res.met is met
    if not met:
        assert any("gold" in u for u in res.unmet)


# --- check_skill_tier -------------------------------------------------------


async def test_check_skill_tier_below_required_is_false():
    q = _queries(get_skill_advancement=AsyncMock(return_value={"athletics": {"tier": "trained"}}))
    assert await mr.check_skill_tier("p1", "Athletics: Expert", queries_mod=q) is False


async def test_check_skill_tier_at_or_above_required_is_true():
    q = _queries(get_skill_advancement=AsyncMock(return_value={"athletics": {"tier": "master"}}))
    assert await mr.check_skill_tier("p1", "Athletics: Expert", queries_mod=q) is True


async def test_check_skill_tier_missing_row_is_untrained():
    q = _queries(get_skill_advancement=AsyncMock(return_value={}))
    assert await mr.check_skill_tier("p1", "Athletics: Trained", queries_mod=q) is False
    assert await mr.check_skill_tier("p1", "Athletics: Untrained", queries_mod=q) is True


# --- check_quest_completed --------------------------------------------------


async def test_check_quest_completed_complete_is_true():
    q = _queries(get_player_quest=AsyncMock(return_value={"status": "complete"}))
    assert await mr.check_quest_completed("p1", "q1", queries_mod=q) is True


async def test_check_quest_completed_active_is_false():
    q = _queries(get_player_quest=AsyncMock(return_value={"status": "active"}))
    assert await mr.check_quest_completed("p1", "q1", queries_mod=q) is False


async def test_check_quest_completed_not_started_is_false():
    q = _queries(get_player_quest=AsyncMock(return_value=None))
    assert await mr.check_quest_completed("p1", "q1", queries_mod=q) is False


# --- _parse_skill_requirement ----------------------------------------------


def test_parse_skill_requirement_ok():
    assert mr._parse_skill_requirement("Athletics: Trained") == ("athletics", "trained")


@pytest.mark.parametrize("bad", ["Athletics", "Athletics: Wizard", ": Trained", "Unknownskill: Trained"])
def test_parse_skill_requirement_malformed_raises(bad):
    with pytest.raises(ValueError):
        mr._parse_skill_requirement(bad)


# --- fail-loud contract paths ----------------------------------------------


async def test_unknown_variant_raises():
    v = Mock()
    v.get_mentor_variant = Mock(side_effect=ValueError("unknown variant"))
    with pytest.raises(ValueError):
        await mr.check_mentor_requirements(
            "p1",
            "mentor_x",
            "bad",
            queries_mod=_queries(),
            content_mod=_content(_npc(_REQS_OPEN)),
            variants_mod=v,
            disposition_mod=_disposition("trusted"),
        )


async def test_variant_taught_by_other_mentor_raises():
    with pytest.raises(ValueError):
        await _check(_REQS_OPEN, variant_mentor="mentor_other")


async def test_missing_mentor_block_raises():
    with pytest.raises(ValueError):
        await mr.check_mentor_requirements(
            "p1",
            "mentor_x",
            "v1",
            queries_mod=_queries(),
            content_mod=_content({"id": "mentor_x"}),
            variants_mod=_variants(),
            disposition_mod=_disposition("trusted"),
        )


async def test_unknown_mentor_npc_raises():
    with pytest.raises(ValueError):
        await mr.check_mentor_requirements(
            "p1",
            "mentor_x",
            "v1",
            queries_mod=_queries(),
            content_mod=_content(None),
            variants_mod=_variants(),
            disposition_mod=_disposition("trusted"),
        )


@pytest.mark.parametrize("requirements", [{"gold": 50}, {"disposition": "friendly"}, {}])
async def test_requirements_missing_required_key_raises_valueerror(requirements):
    """A malformed binding missing disposition/gold fails loud with ValueError (not a bare
    KeyError), so story-003 maps it to ToolError instead of leaking a stack."""
    npc = {"id": "mentor_x", "mentor": {"culture": "X", "training_cycles": 3, "requirements": requirements}}
    with pytest.raises(ValueError):
        await mr.check_mentor_requirements(
            "p1",
            "mentor_x",
            "v1",
            queries_mod=_queries(),
            content_mod=_content(npc),
            variants_mod=_variants(),
            disposition_mod=_disposition("trusted"),
        )


# --- real content integration ----------------------------------------------


async def test_real_drathian_binding_skill_gate():
    """Drathian Hessa gates on Athletics: Trained; an untrained but friendly, rich
    player fails on exactly the skill gate — proves the aggregate reads real content."""
    npcs = json.loads((_CONTENT / "npcs.json").read_text())
    drathian = next(n for n in npcs if n["id"] == "mentor_drathian_warleader")
    res = await mr.check_mentor_requirements(
        "p1",
        "mentor_drathian_warleader",
        "v1",
        queries_mod=_queries(
            get_player=AsyncMock(return_value={"gold": 1000}),
            get_skill_advancement=AsyncMock(return_value={}),
        ),
        content_mod=_content(drathian),
        variants_mod=_variants("mentor_drathian_warleader"),
        disposition_mod=_disposition("friendly"),
    )
    assert res.met is False
    assert len(res.unmet) == 1
    assert "skill" in res.unmet[0] and "Athletics" in res.unmet[0]
