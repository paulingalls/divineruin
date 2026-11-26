"""Registered discovery scenarios and shared Hidden Knowledge inputs."""

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import game_tools
from sample_fixtures import published_payloads

import event_types as E
import patron_synergy
from check_tools import check
from patron_gifts import VEYTHAR_INSIGHT
from query_tools import query_info

LOCATION = "greyvale_ruins_entrance"
ELEMENT = "ruins_journal_fragment"
CLAUSE = {
    "effect": "Investigation checks for hidden information gain +1. The Lorekeeper rewards seekers",
    "status": "active",
    "resolution": "engine",
    "implementation_id": "veythar_hidden_knowledge",
}
RECEIPT = {
    "tag": "hidden_information",
    "applied": True,
    "bonus": 1,
    "clause_id": CLAUSE["implementation_id"],
    "clause_name": "Hidden Knowledge",
    "effect": CLAUSE["effect"],
    "reason": "applied",
}


def discover(skill: str = "investigation") -> dict:
    return {"kind": "discover", "skill": skill, "target": "research station", "hearing_only": False}


SKILL = {
    "kind": "skill",
    "skill": "investigation",
    "difficulty": "easy",
    "context_description": "Review the research methods",
    "hearing_only": False,
    "synergy_context": "none",
}


@contextmanager
def catalog_clause(*, archetypes: tuple[str, ...] = ("rogue", "spy"), **fields: str) -> Iterator[None]:
    catalog = deepcopy(patron_synergy.load_gods())
    veythar = next(god for god in catalog if god["god_id"] == "veythar")
    for archetype in archetypes:
        veythar["layer_4_synergy_matrix"][archetype]["clauses"][0].update(fields)
    with patch.object(patron_synergy, "load_gods", return_value=catalog):
        yield


async def prepare(
    world: SimpleNamespace, archetype: str, *, patron: str = "veythar", index: int = 0, insight: bool = False
) -> None:
    session = world.ctx.userdata
    session.location_id = LOCATION
    session.attempted_discoveries.clear()
    await configure(
        world,
        patron,
        archetype,
        index=index,
        location_id=LOCATION,
        attributes={"intelligence": 10},
        conditions=[],
        flags={"ressa_corrow_scout_token.discovered": True},
        patron_gifts={} if insight else {VEYTHAR_INSIGHT: {"spent": True, "pending": None}},
    )


async def roll_check(world: SimpleNamespace, roll: dict, *, die: int = 14) -> dict:
    call = game_tools(world.ctx.userdata, check)
    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=die)):
        result = await call("check", roll=roll)
    assert "guaranteed_discovery" not in result
    return result


def assert_unchanged(baseline: dict, result: dict, *, outcome: str = "outcome") -> None:
    keys = ("roll", "modifier", "total", "dc", outcome)
    observed = {key: result[key] for key in keys}
    expected = {key: baseline[key] for key in keys}
    assert observed == expected, f"{observed} differs from baseline {expected}"
    assert "context_synergy" not in baseline and "context_synergy" not in result, (baseline, result)


async def paired_discovery(world: SimpleNamespace, roll: dict, *, die: int = 14) -> tuple[dict, dict]:
    with catalog_clause(status="pending", implementation_id="unavailable"):
        baseline = await roll_check(world, roll, die=die)
    world.ctx.userdata.attempted_discoveries.clear()
    return baseline, await roll_check(world, roll, die=die)


async def hidden_knowledge(world: SimpleNamespace, archetype: str) -> None:
    await prepare(world, archetype)
    session = world.ctx.userdata
    with catalog_clause(status="pending"):
        baseline = await roll_check(world, discover())
    assert (baseline["roll"], baseline["modifier"], baseline["total"], baseline["dc"], baseline["outcome"]) == (
        14,
        0,
        14,
        15,
        "not_found",
    )
    assert "context_synergy" not in baseline
    assert not (await row(world, 0))["flags"].get(f"{ELEMENT}.discovered")
    event_start = len(published_payloads(session.room))
    session.attempted_discoveries.clear()
    result = await roll_check(world, discover())
    revealed = (await row(world, 0))["flags"].get(f"{ELEMENT}.discovered")
    keys = ("roll", "modifier", "total", "dc", "outcome")
    observed = {key: result[key] for key in keys} | {"revealed": revealed}
    assert observed == {"roll": 14, "modifier": 1, "total": 15, "dc": 15, "outcome": "discovered", "revealed": True}, (
        observed
    )
    assert result["element_id"] == ELEMENT
    assert result["context_synergy"] == RECEIPT
    events = published_payloads(session.room)[event_start:]
    assert [e["total"] for e in events if e["type"] == E.DICE_ROLL] == [15]
    assert [e["element_id"] for e in events if e["type"] == E.HIDDEN_REVEALED] == [ELEMENT]
    profile = await game_tools(session, query_info)("query_info", kind="patron")
    assert profile["synergy"]["name"] == "Hidden Knowledge"
    assert profile["synergy"]["clauses"] == [CLAUSE]


SCENARIOS = {
    CLAUSE["implementation_id"]: ("patron_synergy:discovery_skill_bonus", hidden_knowledge, [("rogue",), ("spy",)])
}
