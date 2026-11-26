"""Context eligibility and resumed rejection through the registered verbs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance.synergy_discovery import (
    ELEMENT,
    LOCATION,
    RECEIPT,
    SKILL,
    assert_unchanged,
    catalog_clause,
    discover,
    paired_discovery,
    prepare,
    roll_check,
)
from acceptance.test_synergy_context import (
    CIVIC,
    DECEIT,
    MEASURE,
    OATHBREAK,
    SHARED,
    Clause,
    applied,
    paired,
    payload,
    settle_fate,
    setup_actor,
)
from acceptance.test_synergy_context import dev_db_pool as dev_db_pool
from test_aelora_gift import _live_party

import db_content_queries
import patron_synergy
from activate_tools import activate
from check_tools import check
from patron_gifts import VEYTHAR_INSIGHT
from zhael_fate import FATE


def rejected(tag: str, clause: Clause | None = None) -> dict:
    if clause is not None:
        return {**applied(clause), "applied": False, "bonus": 0, "reason": "skill_mismatch"}
    return {
        "tag": tag,
        "applied": False,
        "bonus": 0,
        "clause_id": None,
        "clause_name": None,
        "effect": None,
        "reason": "unheld",
    }


@pytest.mark.parametrize(
    "patron,archetype,kind,skill,tag,held",
    [
        pytest.param("aelora", "warrior", "skill", "religion", SHARED[0], None, id="class"),
        pytest.param("aelora", "cleric", "skill", "persuasion", CIVIC[0], None, id="tag"),
        pytest.param("aelora", "cleric", "skill", "arcana", SHARED[0], SHARED, id="skill"),
        pytest.param("aelora", "paladin", "social", "deception", CIVIC[0], CIVIC, id="social-skill"),
        pytest.param("veythar", "cleric", "skill", "religion", SHARED[0], None, id="patron"),
        pytest.param("none", "cleric", "skill", "religion", SHARED[0], None, id="unbound"),
        pytest.param("valdris", "mage", "skill", "arcana", MEASURE[0], None, id="valdris-unheld"),
        pytest.param("valdris", "mage", "skill", "investigation", OATHBREAK[0], OATHBREAK, id="valdris-skill"),
        pytest.param("valdris", "rogue", "social", "persuasion", DECEIT[0], DECEIT, id="valdris-social-skill"),
    ],
)
async def test_ineligible_context_leaves_total_unchanged(world, patron, archetype, kind, skill, tag, held):
    await setup_actor(world, patron, archetype)
    baseline, result = await paired(world, kind, skill, tag)
    assert "context_synergy" not in baseline
    assert result["total"] == baseline["total"]
    assert result["context_synergy"] == rejected(tag, held)


@pytest.mark.parametrize(
    "field,value,skill,bonus",
    [
        ("status", "pending", "religion", 0),
        ("resolution", "narrated", "religion", 0),
        ("skill", None, "arcana", 1),
        ("bonus", 2, "religion", 2),
    ],
    ids=["pending", "narrated", "unrestricted", "authored-bonus"],
)
async def test_clauses_obey_catalog_eligibility(world, monkeypatch, field, value, skill, bonus):
    await setup_actor(world, "aelora", "cleric")
    catalog = deepcopy(patron_synergy.load_gods())
    aelora = next(god for god in catalog if god["god_id"] == "aelora")
    aelora["layer_4_synergy_matrix"]["cleric"]["clauses"][0][field] = value
    monkeypatch.setattr(patron_synergy, "load_gods", lambda: catalog)
    baseline, result = await paired(world, "skill", skill, SHARED[0])
    assert result["total"] == baseline["total"] + bonus
    assert result["context_synergy"] == ({**applied(SHARED), "bonus": bonus} if bonus else rejected(SHARED[0]))


async def test_eligible_context_stays_absent_on_tier_auto_failure(world):
    await setup_actor(world, "aelora", "paladin")
    call = game_tools(world.ctx.userdata, check)
    result = await call("check", roll={**payload("social", "persuasion", CIVIC[0]), "difficulty": "extreme"})
    assert (result["outcome"], result["roll"], result["total"]) == ("failure", 0, 0)
    assert "context_synergy" not in result


async def test_fate_settles_rejected_context(world):
    result = await settle_fate(world, "skill", "religion", CIVIC[0], "reroll")
    assert (result["roll"], result["total"], result["context_synergy"]) == (13, 14, rejected(CIVIC[0]))


@pytest.mark.parametrize("stored_tag", ["current", "legacy", "invalid"])
async def test_insight_replays_skill_context(world, stored_tag):
    await setup_actor(world, "veythar", "cleric")
    call = game_tools(world.ctx.userdata, check, activate)
    with patch("check_resolution.dice_roll", side_effect=[SimpleNamespace(total=2), SimpleNamespace(total=13)]):
        failed = await call("check", roll=payload("skill", "religion", SHARED[0]))
        assert failed["reroll_offer"]
        assert failed["context_synergy"] == rejected(SHARED[0])
        if stored_tag == "legacy":
            await world.pool.execute(
                "UPDATE players SET data=data #- $2::text[] WHERE player_id=$1",
                world.ids[0],
                ["patron_gifts", VEYTHAR_INSIGHT, "pending", "synergy_context"],
            )
        if stored_tag == "invalid":
            await world.pool.execute(
                "UPDATE players SET data=jsonb_set(data, $2::text[], 'null'::jsonb) WHERE player_id=$1",
                world.ids[0],
                ["patron_gifts", VEYTHAR_INSIGHT, "pending", "synergy_context"],
            )
            with pytest.raises(ValueError, match="synergy_context"):
                await call("activate", id=VEYTHAR_INSIGHT)
            return
        result = await call("activate", id=VEYTHAR_INSIGHT)
    assert result["total"] - failed["total"] == 11
    if stored_tag == "current":
        assert result["context_synergy"] == rejected(SHARED[0])
    else:
        assert "context_synergy" not in result


@pytest.mark.parametrize(
    "exclusion,archetype",
    [
        ("skill", "rogue"),
        ("skill", "spy"),
        ("perception", "rogue"),
        ("perception", "spy"),
        ("patron", "rogue"),
        ("patron", "spy"),
        ("class", "mage"),
    ],
)
async def test_hidden_knowledge_exclusions(world: SimpleNamespace, exclusion: str, archetype: str) -> None:
    await prepare(world, archetype, patron="kaelen" if exclusion == "patron" else "veythar")
    skill = "perception" if exclusion == "perception" else "investigation"
    roll = SKILL if exclusion == "skill" else discover(skill)
    baseline, result = await paired_discovery(world, roll, die=11)
    assert_unchanged(baseline, result)


@pytest.mark.parametrize(
    "fields",
    [{"status": "pending"}, {"resolution": "narrated"}, {"implementation_id": "another_clause"}],
    ids=["pending", "narrated", "unheld"],
)
async def test_hidden_knowledge_clause_eligibility(world: SimpleNamespace, fields: dict[str, str]) -> None:
    await prepare(world, "rogue")
    with catalog_clause(status="pending", implementation_id="unavailable"):
        baseline = await roll_check(world, discover())
    world.ctx.userdata.attempted_discoveries.clear()
    with catalog_clause(archetypes=("rogue",), **fields):
        result = await roll_check(world, discover())
    assert_unchanged(baseline, result)


async def test_hidden_knowledge_tier_auto_failure(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    await prepare(world, "rogue")
    location = await db_content_queries.get_location(LOCATION)
    assert location is not None
    next(e for e in location["hidden_elements"] if e["id"] == ELEMENT)["dc"] = 24
    monkeypatch.setattr(db_content_queries, "get_location", AsyncMock(return_value=location))
    result = await roll_check(world, discover())
    assert (result["outcome"], result["roll"], result["total"], result["dc"]) == ("automatic_failure", 0, 0, 24)
    assert "context_synergy" not in result


async def test_insight_repeats_hidden_knowledge_discovery(world: SimpleNamespace) -> None:
    await prepare(world, "rogue", insight=True)
    initial = await roll_check(world, discover(), die=2)
    call = game_tools(world.ctx.userdata, activate)
    stored = (await row(world, 0))["patron_gifts"][VEYTHAR_INSIGHT]
    assert (stored["pending"]["kind"], stored["pending"]["element_id"], stored["pending"]["dc"]) == (
        "discover",
        ELEMENT,
        15,
    )
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=14)):
        result = await call("activate", id=VEYTHAR_INSIGHT)
    player = await row(world, 0)
    assert (initial["total"], initial["outcome"], result["total"], result["outcome"]) == (
        3,
        "not_found",
        15,
        "discovered",
    )
    assert initial["context_synergy"] == result["context_synergy"] == RECEIPT
    assert result["element_id"] == ELEMENT and player["flags"][f"{ELEMENT}.discovered"]
    assert player["patron_gifts"][VEYTHAR_INSIGHT] == {"spent": True, "pending": None}


async def test_insight_skill_reroll_excludes_hidden_knowledge(world: SimpleNamespace) -> None:
    async def run() -> tuple[dict, dict]:
        await prepare(world, "rogue", insight=True)
        initial = await roll_check(world, SKILL, die=2)
        assert initial["reroll_offer"]
        call = game_tools(world.ctx.userdata, activate)
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=14)):
            result = await call("activate", id=VEYTHAR_INSIGHT)
        return initial, result

    with catalog_clause(status="pending"):
        initial_before, reroll_before = await run()
    initial, reroll = await run()
    assert_unchanged(initial_before, initial)
    assert_unchanged(reroll_before, reroll)


@pytest.mark.parametrize("keep,faces", [("original", (14, 12)), ("reroll", (12, 14))])
async def test_fate_settles_hidden_knowledge_for_guest(
    world: SimpleNamespace, keep: str, faces: tuple[int, int]
) -> None:
    await prepare(world, "mage", patron="zhael")
    await prepare(world, "rogue", index=1)
    session = world.ctx.userdata
    host, guest = world.ids
    lifecycle = _live_party(session, host, guest)
    call = game_tools(session, check, activate)
    try:
        with patch("check_resolution.dice_roll", side_effect=[SimpleNamespace(total=face) for face in faces]):
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                response = await call("check", roll=discover())
            assert "guaranteed_discovery" not in response
            offer = response["fate_offer"]
            assert offer["roller_id"] == guest and offer["eligible_followers"] == [host]
            args = {"id": FATE, "offer_id": offer["offer_id"]}
            with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                shown = await call("activate", **args)
                result = await call("activate", **args, keep=keep)
        player = await row(world, 1)
        assert (shown[keep]["total"], result["roll"], result["total"], result["outcome"]) == (15, 14, 15, "discovered")
        assert result["context_synergy"] == RECEIPT
        assert result["element_id"] == ELEMENT and player["flags"][f"{ELEMENT}.discovered"]
    finally:
        await lifecycle.aclose()
