"""Foretold Words through the registered social, patron and Fate commands."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from _zhael_fate_skills_fixtures import FATE, ORIGIN, SOCIAL
from _zhael_fate_skills_fixtures import party as party
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolContext, ToolError
from sample_fixtures import make_context, published_payloads

import db_mutations
import db_queries
from check_tools import check
from query_tools import query_info

CLAUSE = "zhael_foretold_words"
NPC = SOCIAL["npc_id"]
OTHER_NPC = "elder_yanna"
ATTEMPT = {**SOCIAL, "difficulty": "moderate"}
FORETELL = {key: value for key, value in ATTEMPT.items() if key != "synergy_context"} | {"kind": "foretell_social"}


async def follower(world, archetype="bard", *, patron="zhael", fate=False) -> None:
    await configure(
        world,
        patron,
        archetype,
        conditions=[],
        location_id=ORIGIN,
        attributes={"charisma": 10},
        patron_gifts={FATE: {"uses_spent": 0 if fate else 1}},
    )
    await db_mutations.set_npc_disposition(NPC, world.ids[0], "neutral", "setup")


async def ledger(world, npc=NPC, *, session=None) -> list:
    return await world.pool.fetch(
        "SELECT data->'binding' AS binding FROM zhael_foretold_words "
        "WHERE player_id=$1 AND npc_id=$2 AND session_id=$3",
        world.ids[0],
        npc,
        session or world.ctx.userdata.session_id,
    )


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_registered_strict_schema_includes_foretelling(vendor) -> None:
    [schema] = ToolContext([check]).parse_function_tools(vendor, strict=True)
    params = schema["function"]["parameters"] if vendor == "openai" else schema["input_schema"]
    variants = (params["$defs"][branch["$ref"].split("/")[-1]] for branch in params["properties"]["roll"]["anyOf"])
    [forecast] = [branch for branch in variants if branch["properties"]["kind"]["const"] == "foretell_social"]
    assert set(forecast["required"]) == {"kind", "npc_id", "skill", "difficulty"}
    assert set(forecast["properties"]["skill"]["enum"]) == {"persuasion", "deception", "intimidation"}


async def forecast_and_attempt(world, archetype) -> None:
    session = world.ctx.userdata
    await follower(world, archetype)
    call = game_tools(session, check)
    with patch("check_resolution.dice_roll", return_value=_d20(13)) as die:
        forecast = await call("check", roll=FORETELL)
        die.assert_not_called()
        assert (forecast["clause_id"], forecast["clause_name"]) == (CLAUSE, "Foretold Words")
        assert (forecast["npc_id"], forecast["skill"], forecast["dc"]) == (NPC, "persuasion", 12)
        assert "12" in forecast["dm_cue"] and "Tell" in forecast["dm_cue"]
        assert not published_payloads(session.room)
        assert await db_queries.get_npc_disposition(NPC, world.ids[0]) == "neutral"
        assert (await ledger(world))[0]["binding"] != "null"
        result = await call("check", roll=ATTEMPT)
        assert (result["outcome"], result["total"], result["dc"], result["margin"]) == ("success", 13, 12, 1)
        assert (result["previous_disposition"], result["new_disposition"]) == ("neutral", "neutral")
        assert (result["clause_id"], result["clause_name"]) == (CLAUSE, "Foretold Words")
        assert "clause_id" not in await call("check", roll=ATTEMPT)
    [spent] = await ledger(world)
    assert spent["binding"] == "null"


SCENARIOS = {CLAUSE: ("zhael_foretold_words:foretell", forecast_and_attempt, [("bard",), ("diplomat",)])}


@pytest.mark.parametrize(
    "original,current,dc,verdict,difficulty",
    [("neutral", "unfriendly", 12, "success", "hard"), ("unfriendly", "neutral", 15, "failure", "moderate")],
)
async def test_disposition_and_difficulty_can_change(world, original, current, dc, verdict, difficulty) -> None:
    await follower(world)
    call = game_tools(world.ctx.userdata, check)
    await db_mutations.set_npc_disposition(NPC, world.ids[0], original, "setup")
    assert (await call("check", roll=FORETELL))["dc"] == dc
    await db_mutations.set_npc_disposition(NPC, world.ids[0], current, "changed standing")
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        result = await call("check", roll={**ATTEMPT, "difficulty": difficulty})
    assert (result["dc"], result["outcome"], result["margin"], result["previous_disposition"]) == (
        dc,
        verdict,
        13 - dc,
        current,
    )


async def test_budget_by_actor_npc_and_session(world, party) -> None:
    call, _ = party
    await follower(world)
    original_session = world.ctx.userdata.session_id
    assert (await call(0, "query_info", kind="patron"))["foretold_words"]["foretold_npcs"] == []
    await call(0, "check", roll=FORETELL)
    with pytest.raises(ToolError, match="already foretold"):
        await call(0, "check", roll=FORETELL)
    await db_mutations.set_npc_disposition(OTHER_NPC, world.ids[0], "neutral", "setup")
    await call(0, "check", roll={**FORETELL, "npc_id": OTHER_NPC})
    await configure(world, "zhael", "diplomat", index=1, patron_gifts={FATE: {"uses_spent": 1}})
    await db_mutations.set_npc_disposition(NPC, world.ids[1], "unfriendly", "setup")
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        guest = await call(1, "check", roll=ATTEMPT)
    assert guest.get("dc") == 15 and "clause_id" not in guest, guest
    await db_mutations.set_npc_disposition(NPC, world.ids[1], "neutral", "setup")
    await call(1, "check", roll=FORETELL)

    fresh = make_context(player_id=world.ids[0]).userdata
    next_session = fresh.session_id
    fresh.session_id = original_session
    reload_call = game_tools(fresh, check, query_info)
    projection = (await reload_call("query_info", kind="patron"))["foretold_words"]
    assert projection["clause_id"] == CLAUSE and "foretell_social" in projection["invocation_hint"]
    assert {row["npc_id"]: row["binding"] for row in projection["foretold_npcs"]} == {
        NPC: {"skill": "persuasion", "dc": 12},
        OTHER_NPC: {"skill": "persuasion", "dc": 12},
    }
    with pytest.raises(ToolError, match="already foretold"):
        await reload_call("check", roll=FORETELL)
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        assert (await reload_call("check", roll=ATTEMPT))["clause_id"] == CLAUSE
    rows = (await reload_call("query_info", kind="patron"))["foretold_words"]["foretold_npcs"]
    assert {"npc_id": NPC, "binding": None} in rows
    guest_rows = (await call(1, "query_info", kind="patron"))["foretold_words"]["foretold_npcs"]
    assert guest_rows == [{"npc_id": NPC, "binding": {"skill": "persuasion", "dc": 12}}]
    with pytest.raises(ToolError, match="already foretold"):
        await reload_call("check", roll=FORETELL)

    fresh.session_id = next_session
    assert (await reload_call("query_info", kind="patron"))["foretold_words"]["foretold_npcs"] == []
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        assert "clause_id" not in await reload_call("check", roll={**ATTEMPT, "npc_id": OTHER_NPC})
    await reload_call("check", roll=FORETELL)
    assert (await ledger(world, session=next_session))[0]["binding"] != "null"
    assert (await ledger(world, session=original_session))[0]["binding"] == "null"

    await db_mutations.set_npc_disposition(OTHER_NPC, world.ids[0], "neutral", "setup")
    await reload_call("check", roll={**FORETELL, "npc_id": OTHER_NPC})
    with patch("check_resolution.dice_roll", return_value=_d20(13)):
        await reload_call("check", roll={**ATTEMPT, "npc_id": OTHER_NPC})
    assert (await ledger(world, OTHER_NPC, session=original_session))[0]["binding"] != "null"


@pytest.mark.parametrize(
    "patron,archetype,npc,error",
    [
        ("zhael", "marshal", NPC, "Foretold Words"),
        ("veythar", "bard", NPC, "Foretold Words"),
        ("zhael", "bard", "missing_social_npc", "Unknown NPC"),
    ],
)
async def test_refuses_ineligible_actor_or_unknown_npc(world, patron, archetype, npc, error) -> None:
    await follower(world, archetype, patron=patron)
    call = game_tools(world.ctx.userdata, check)
    with patch("check_resolution.dice_roll") as die, pytest.raises(ToolError, match=error):
        await call("check", roll={**FORETELL, "npc_id": npc})
    die.assert_not_called()
    assert not await ledger(world, npc)
    assert not published_payloads(world.ctx.userdata.room)


async def test_forecast_binds_the_skill_before_dice(world) -> None:
    await follower(world)
    call = game_tools(world.ctx.userdata, check)
    await call("check", roll=FORETELL)
    with patch("check_resolution.dice_roll", return_value=_d20(13)) as die:
        with pytest.raises(ToolError, match="persuasion"):
            await call("check", roll={**ATTEMPT, "skill": "deception"})
        die.assert_not_called()
        assert (await call("check", roll=ATTEMPT))["clause_id"] == CLAUSE


@pytest.mark.parametrize("keep,total,verdict", [("original", 11, "failure"), ("reroll", 13, "success")])
async def test_fate_settles_against_the_forecast_once(world, party, keep, total, verdict) -> None:
    call, _ = party
    await follower(world, fate=True)
    await call(0, "check", roll=FORETELL)
    with patch("check_resolution.dice_roll", side_effect=[_d20(11), _d20(13)]):
        offer = (await call(0, "check", roll=ATTEMPT))["fate_offer"]
        assert (await ledger(world))[0]["binding"] != "null"
        assert not published_payloads(world.ctx.userdata.room)
        await db_mutations.set_npc_disposition(NPC, world.ids[0], "unfriendly", "changed while held")
        choice = {"id": FATE, "offer_id": offer["offer_id"]}
        await call(0, "activate", **choice)
        assert (await ledger(world))[0]["binding"] != "null"
        result = await call(0, "activate", **choice, keep=keep)
        with pytest.raises(ToolError, match="current Fate"):
            await call(0, "activate", **choice, keep=keep)
    assert (result["total"], result["dc"], result["outcome"], result["margin"]) == (total, 12, verdict, total - 12)
    assert result["clause_id"] == CLAUSE
    assert (await ledger(world))[0]["binding"] == "null"
    events = published_payloads(world.ctx.userdata.room)
    assert sum(event["type"] == "dice_roll" for event in events) == 1


async def test_held_roll_cancels_if_another_connection_settled_the_binding(world, party) -> None:
    call, _ = party
    await follower(world, fate=True)
    await call(0, "check", roll=FORETELL)
    reconnected = make_context(player_id=world.ids[0]).userdata
    reconnected.session_id = world.ctx.userdata.session_id
    reconnect_call = game_tools(reconnected, check)
    with patch("check_resolution.dice_roll", side_effect=[_d20(11), _d20(18), _d20(13)]):
        offer = (await call(0, "check", roll=ATTEMPT))["fate_offer"]
        choice = {"id": FATE, "offer_id": offer["offer_id"]}
        await call(0, "activate", **choice)
        assert (await reconnect_call("check", roll=ATTEMPT))["clause_id"] == CLAUSE
        result = await call(0, "activate", **choice, keep="reroll")
    assert result["outcome"] == "cancelled" and "pending check" in result["reason"]
    assert world.ctx.userdata.fate_offer is None
    assert await db_queries.get_npc_disposition(NPC, world.ids[0]) == "neutral"
    assert not published_payloads(world.ctx.userdata.room)
