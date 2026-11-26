"""Context eligibility and resumed rejection through the registered verbs."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance.test_synergy_context import CIVIC, SHARED, Clause, applied, paired, payload, settle_fate, setup_actor
from acceptance.test_synergy_context import dev_db_pool as dev_db_pool

import patron_synergy
from activate_tools import activate
from check_tools import check
from patron_gifts import VEYTHAR_INSIGHT


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
