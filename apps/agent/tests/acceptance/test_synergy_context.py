"""Narrative patron bonuses through registered checks and patron discovery."""

from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from test_aelora_gift import _live_party

import db
import db_mutations
from activate_tools import activate
from check_tools import check
from query_tools import query_info
from zhael_fate import FATE

Clause = tuple[str, str, str, str, str | None]

NPC = "guildmaster_torin"
MERCHANT = "aelora_guildmaster_dara"
SHARED = (
    "shared_meal",
    "aelora_shared_table",
    "Shared Table",
    "Gain +1 Religion when blessing a shared meal.",
    "religion",
)
CIVIC = (
    "community_duties",
    "aelora_civic_promise",
    "Civic Promise",
    "Gain +1 Persuasion when negotiating a community’s shared duties.",
    "persuasion",
)
HEARTH = (
    "household_omen",
    "aelora_hearth_omen",
    "Hearth Omen",
    "Gain +1 Insight when interpreting a household omen.",
    "insight",
)
COMMERCE = ("commerce", "aelora_commerce_persuasion", "Honest Hustle", "Commerce Persuasion +1.", "persuasion")
GROVE = (
    "sacred_grove",
    "thyra_wild_covenant",
    "Wild Covenant",
    "Gain +1 Religion when honoring a sacred grove.",
    "religion",
)
SEASONAL = (
    "seasonal_omen",
    "thyra_seasonal_omen",
    "Seasonal Omen",
    "Gain +1 Nature when interpreting a seasonal omen.",
    "nature",
)
SHORELINE = (
    "coast_shelter",
    "nythera_shoreline_keeper",
    "Shoreline Keeper",
    "Gain +1 Survival when finding safe shelter along an unfamiliar coast.",
    "survival",
)
HARBOR = (
    "port_passage",
    "nythera_harbor_courtesy",
    "Harbor Courtesy",
    "Gain +1 Persuasion when seeking peaceful passage through an unfamiliar port.",
    "persuasion",
)
VOYAGER = (
    "vessel_repair",
    "nythera_voyagers_tools",
    "Voyager's Tools",
    "Gain +1 to checks to repair a vessel during a journey.",
    None,
)
MENDER = (
    "sanctuary_repair",
    "orenthel_menders_dawn",
    "Mender's Dawn",
    "Gain +1 to checks to repair equipment for a damaged sanctuary.",
    None,
)
GREEN_MORNING = (
    "blighted_grove",
    "orenthel_green_morning",
    "Green Morning",
    "Gain +1 Nature when restoring a blighted grove.",
    "nature",
)
RECONCILIATION = (
    "wounded_enemy_care",
    "orenthel_reconciliation",
    "Reconciliation",
    "Gain +1 Persuasion when negotiating care for wounded enemies.",
    "persuasion",
)


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


def payload(kind: str, skill: str, tag: str = "none", *, npc_id: str = NPC) -> dict:
    roll = {"kind": kind, "skill": skill, "difficulty": "easy", "synergy_context": tag}
    if kind == "social":
        return {**roll, "npc_id": npc_id}
    return {**roll, "context_description": "Observe the community’s customs", "hearing_only": False}


async def setup_actor(world: SimpleNamespace, patron: str, archetype: str, *, index: int = 0) -> None:
    await configure(
        world,
        patron,
        archetype,
        index=index,
        location_id=world.ctx.userdata.location_id,
        attributes={"charisma": 12, "wisdom": 10, "intelligence": 10, "strength": 10},
        conditions=[],
    )


async def paired(world: SimpleNamespace, kind: str, skill: str, tag: str, *, npc_id: str = NPC) -> tuple[dict, dict]:
    call = game_tools(world.ctx.userdata, check)
    results = []
    for context in ("none", tag):
        if kind == "social":
            await db_mutations.set_npc_disposition(npc_id, world.ids[0], "neutral", "setup")
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=11)):
            results.append(await call("check", roll=payload(kind, skill, context, npc_id=npc_id)))
    return results[0], results[1]


def applied(clause: Clause) -> dict:
    tag, clause_id, name, effect, _ = clause
    return {
        "tag": tag,
        "applied": True,
        "bonus": 1,
        "clause_id": clause_id,
        "clause_name": name,
        "effect": effect,
        "reason": "applied",
    }


async def context_scenario(
    world: SimpleNamespace,
    patron: str,
    archetype: str,
    kind: str,
    skill: str,
    clause: Clause,
    npc_id: str = NPC,
) -> None:
    tag, clause_id, _, effect, declared_skill = clause
    await setup_actor(world, patron, archetype)
    assert not world.ctx.userdata.ally_present_for(world.ids[0])
    baseline, result = await paired(world, kind, skill, tag, npc_id=npc_id)
    assert result["total"] == baseline["total"] + 1
    assert baseline["total"] == (12 if skill == "persuasion" else 11)
    assert "context_synergy" not in baseline
    assert "gift_name" not in baseline and "gift_name" not in result
    assert result["roll"] == baseline["roll"] == 11
    assert result["dc"] == baseline["dc"]
    assert result["margin"] == baseline["margin"] + 1
    assert result["outcome"] == ("success" if result["margin"] >= 0 else "failure")
    if kind == "skill":
        assert result["modifier"] == baseline["modifier"] + 1
    assert result["context_synergy"] == applied(clause)
    call = game_tools(world.ctx.userdata, query_info)
    profile = await call("query_info", kind="patron")
    active = next(row for row in profile["synergy"]["clauses"] if row.get("implementation_id") == clause_id)
    assert active == {
        "status": "active",
        "resolution": "engine",
        "implementation_id": clause_id,
        "kind": "context_check",
        "synergy_context": tag,
        "skill": declared_skill,
        "bonus": 1,
        "effect": effect,
    }


SCENARIOS = {
    "aelora_shared_table": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("aelora", "cleric", "skill", "religion", SHARED)],
    ),
    "aelora_civic_promise": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("aelora", "paladin", "social", "persuasion", CIVIC)],
    ),
    "aelora_hearth_omen": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("aelora", "oracle", "skill", "insight", HEARTH)],
    ),
    "aelora_commerce_persuasion": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [
            ("aelora", "rogue", "skill", "persuasion", COMMERCE),
            ("aelora", "rogue", "social", "persuasion", COMMERCE, MERCHANT),
        ],
    ),
    "thyra_wild_covenant": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("thyra", "paladin", "skill", "religion", GROVE)],
    ),
    "thyra_seasonal_omen": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("thyra", "oracle", "skill", "nature", SEASONAL)],
    ),
    "nythera_shoreline_keeper": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("nythera", "warden", "skill", "survival", SHORELINE)],
    ),
    "nythera_harbor_courtesy": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [
            ("nythera", "diplomat", "skill", "persuasion", HARBOR),
            ("nythera", "diplomat", "social", "persuasion", HARBOR),
        ],
    ),
    "nythera_voyagers_tools": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [
            ("nythera", "artificer", "skill", "athletics", VOYAGER),
            ("nythera", "artificer", "skill", "crafting", VOYAGER),
        ],
    ),
    "orenthel_menders_dawn": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [
            ("orenthel", "artificer", "skill", "athletics", MENDER),
            ("orenthel", "artificer", "skill", "crafting", MENDER),
        ],
    ),
    "orenthel_green_morning": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [("orenthel", "warden", "skill", "nature", GREEN_MORNING)],
    ),
    "orenthel_reconciliation": (
        "patron_synergy:context_skill_bonus",
        context_scenario,
        [
            ("orenthel", "diplomat", "skill", "persuasion", RECONCILIATION),
            ("orenthel", "diplomat", "social", "persuasion", RECONCILIATION),
        ],
    ),
}


async def test_nythera_warden_does_not_hold_orenthel_context(world: SimpleNamespace) -> None:
    await setup_actor(world, "nythera", "warden")
    baseline, result = await paired(world, "skill", "survival", "blighted_grove")

    for field in ("total", "roll", "modifier", "dc", "margin", "outcome"):
        assert result[field] == baseline[field]
    assert "context_synergy" not in baseline
    assert result["context_synergy"] == {
        "tag": "blighted_grove",
        "applied": False,
        "bonus": 0,
        "clause_id": None,
        "clause_name": None,
        "effect": None,
        "reason": "unheld",
    }


async def test_household_omen_stacks_with_bond(world: SimpleNamespace) -> None:
    session = world.ctx.userdata
    host = world.ids[0]
    await setup_actor(world, "aelora", "oracle")
    lifecycle = _live_party(session, *world.ids)
    try:
        assert session.allies_present_for(host) == 1
        with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
            baseline, result = await paired(world, "skill", "insight", HEARTH[0])
    finally:
        await lifecycle.aclose()

    assert (baseline["total"], result["total"]) == (12, 13)
    assert baseline["gift_name"] == result["gift_name"] == "Hearthkeeper's Bond"
    assert "context_synergy" not in baseline
    assert result["context_synergy"] == applied(HEARTH)
    assert result["roll"] == baseline["roll"] == 11
    assert result["dc"] == baseline["dc"]
    assert result["margin"] == baseline["margin"] + 1
    assert result["modifier"] == baseline["modifier"] + 1


async def settle_fate(world: SimpleNamespace, kind: str, skill: str, tag: str, keep: str) -> dict:
    session = world.ctx.userdata
    host, guest = world.ids
    await setup_actor(world, "zhael", "mage")
    await setup_actor(world, "aelora", "paladin" if kind == "social" else "cleric", index=1)
    if kind == "social":
        await db_mutations.set_npc_disposition(NPC, guest, "neutral", "setup")
    lifecycle = _live_party(session, host, guest)
    call = game_tools(session, check, activate)
    try:
        with patch("check_resolution.dice_roll", side_effect=[SimpleNamespace(total=11), SimpleNamespace(total=13)]):
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                offer = (await call("check", roll=payload(kind, skill, tag)))["fate_offer"]
            assert offer["roller_id"] == guest
            assert offer["eligible_followers"] == [host]
            args = {"id": FATE, "offer_id": offer["offer_id"]}
            with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                shown = await call("activate", **args)
                result = await call("activate", **args, keep=keep)
            assert shown[keep]["die"] == result["roll"]
            assert shown[keep]["total"] == result["total"]
            return result
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize(
    "kind,skill,clause,keep,die,total",
    [("skill", "religion", SHARED, "original", 11, 13), ("social", "persuasion", CIVIC, "reroll", 13, 16)],
)
async def test_fate_settles_applied_context(world, kind, skill, clause, keep, die, total):
    result = await settle_fate(world, kind, skill, clause[0], keep)
    assert (result["roll"], result["total"], result["context_synergy"]) == (die, total, applied(clause))
