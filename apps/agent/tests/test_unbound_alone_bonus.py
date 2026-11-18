"""Unbound skill checks through the production check routes."""

import json
from typing import cast as type_cast
from unittest.mock import MagicMock, patch

import pytest
from _unbound_path_fixtures import world as world
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import db_mutations_conditions
import db_mutations_skill_advancement
import db_queries
import rules_engine
from check_skill import _check_skill_run
from check_tools import _check_impl
from session_data import CompanionState
from skill_check_effects import SkillCheckEffects
from tools._discover_fixtures import _roll


async def check(w, skill="athletics"):
    with patch("check_resolution.dice_roll", return_value=_roll(11)):
        return json.loads(await _check_impl(w.ctx, "skill", skill=skill, difficulty="moderate"))


@pytest.mark.parametrize("patron", ["none", None])
async def test_all_skills_include_alone_bonus(world, patron):
    w = world
    await w.pool.execute(
        "UPDATE players SET data=jsonb_set(data || jsonb_build_object('player_id', $1::text), '{divine_favor,patron}', $2::jsonb) WHERE player_id=$1",
        w.ids[0],
        json.dumps(patron),
    )
    for skill in rules_engine.SKILLS:
        result = await check(w, skill)
        assert {key: result[key] for key in ("roll", "modifier", "total", "margin", "outcome")} == {
            "roll": 11,
            "modifier": 1,
            "total": 12,
            "margin": 0,
            "outcome": "success",
        }
        event = [p for p in published_payloads(w.ctx.userdata.room) if p["type"] == "dice_roll"][-1]
        assert event["skill"] == skill and event["total"] == 12


async def test_reroll_resolution_includes_alone_bonus(world):
    w = world
    effects = SkillCheckEffects()
    async with w.db.transaction() as conn:
        player = await db_queries.get_player(w.ids[0], conn=conn, for_update=True)
        with patch("check_resolution.dice_roll", return_value=_roll(11)):
            result = json.loads(
                await _check_skill_run(
                    w.ctx,
                    "athletics",
                    "moderate",
                    "reroll",
                    hearing_only=False,
                    queries=db_queries,
                    mutations=db_mutations_skill_advancement,
                    db_mod=w.db,
                    conditions_mutations=db_mutations_conditions,
                    effects=effects,
                    conn=conn,
                    locked_player=player,
                    reroll_dc=12,
                )
            )
    assert (result["modifier"], result["total"], result["outcome"]) == (1, 12, "success")
    assert effects.events[0][1]["total"] == 12


async def test_presence_and_follower_exclude_bonus(world):
    w = world
    session = w.ctx.userdata
    assert (await check(w))["total"] == 12
    session.companion = CompanionState(id="ally", name="Ally", is_present=True)
    assert (await check(w))["total"] == 11
    session.companion.is_present = False
    assert (await check(w))["total"] == 12
    lifecycle = _live_party(session, *w.ids)
    handlers = dict(call.args for call in type_cast(MagicMock, lifecycle.room).on.call_args_list)
    try:
        assert (await check(w))["total"] == 11
        handlers["participant_disconnected"](lifecycle.room.remote_participants[w.ids[1]])
        assert session.party.contains(w.ids[1])
        assert (await check(w))["total"] == 12
        handlers["participant_connected"](lifecycle.room.remote_participants[w.ids[1]])
        handlers["participant_disconnected"](lifecycle.room.remote_participants[w.ids[0]])
        with session._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
            assert (await check(w))["total"] == 12
        await w.pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor,patron}', '\"valdris\"') WHERE player_id=$1",
            w.ids[1],
        )
        with session._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
            assert (await check(w))["total"] == 11
    finally:
        await lifecycle.aclose()
