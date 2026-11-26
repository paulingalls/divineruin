"""Lawful Command through the registered combat and patron tools."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from sample_fixtures import CONTENT_ROOT, FIXED_NOW, make_context, make_mock_room, published_payloads

import db
import db_content_queries
import db_mutations
from creation_rules import build_character_data
from mode_tools import enter_mode
from query_tools import query_info

TEMPLE = "accord_temple_row"
GUILD = "accord_guild_hall"
MARKET = "accord_market_square"
CLAUSE = "valdris_lawful_command"
PROFILE = json.loads((CONTENT_ROOT / "packages/shared/fixtures/god_profiles.json").read_text())["lawful_command"]
AWARD = {"id": CLAUSE, "name": "Lawful Command", "bonus": 1}


@pytest.fixture
async def dev_db_pool(reset_db_pool: str) -> asyncpg.Pool:
    return await db.get_pool()


@asynccontextmanager
async def location_tags(pool: asyncpg.Pool, location: str, override: bool | None) -> AsyncIterator[None]:
    if override is None:
        yield
        return

    original = await pool.fetchval("SELECT data FROM locations WHERE id=$1", location)
    row = json.loads(original)
    row["tags"] = [tag for tag in row["tags"] if tag != "sanctuary"]
    if override:
        row["tags"].append("sanctuary")
    await pool.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", location, json.dumps(row))
    try:
        yield
    finally:
        await pool.execute("UPDATE locations SET data=$2::jsonb WHERE id=$1", location, original)


async def test_only_shipped_sanctuaries_are_tagged(dev_db_pool: asyncpg.Pool) -> None:
    with patch.object(db, "_cache_get", AsyncMock(return_value=None)), patch.object(db, "_cache_set", AsyncMock()):
        locations = await db_content_queries.get_all_locations(conn=dev_db_pool)
        assert {
            "thornveld_old_growth_grove",
            "keldaran_southern_pass",
            "sunward_tidal_shore",
        } <= locations.keys()
        assert {key for key, row in locations.items() if "sanctuary" in row["tags"]} == {TEMPLE, GUILD}
        for location in (TEMPLE, GUILD):
            row = await db_content_queries.get_location(location, conn=dev_db_pool)
            assert row is not None and "sanctuary" in row["tags"]


async def start_at_sanctuary(
    world: SimpleNamespace,
    location: str,
    initiator: dict,
    sanctuary: bool,
    bonus: int,
    *,
    override: bool | None = None,
    patron: str = "valdris",
    archetype: str = "marshal",
    guest: bool = False,
) -> None:
    host, ally = world.ids
    candidate = ally if guest else host
    for pid in world.ids:
        role, deity = (archetype, patron) if pid == candidate else ("warrior", "kaelen")
        row = build_character_data(pid, "human", role, deity, "", created_at=FIXED_NOW)
        row["attributes"]["dexterity"] = 14
        await world.pool.execute("UPDATE players SET data=$2::jsonb WHERE player_id=$1", pid, json.dumps(row))

    room = make_mock_room()
    session = make_context(host, location, room, party_member_ids=[ally]).userdata
    call = game_tools(session, enter_mode, query_info)
    host_roll, ally_roll = 10, 10 if guest else 11
    rolls = iter((host_roll, ally_roll))
    try:
        with (
            patch.object(db, "_cache_get", AsyncMock(return_value=None)),
            patch.object(db, "_cache_set", AsyncMock()),
            patch("combat_agent.create_combat_agent") as factory,
            patch(
                "combat_resolution.dice_roll",
                side_effect=lambda *_args, **_kwargs: SimpleNamespace(total=next(rolls, 1)),
            ),
        ):
            async with location_tags(world.pool, location, override):
                projection = await call("query_info", kind="patron")
                _, result = await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair", **initiator)

        saved = await db_mutations.load_combat_state(result["combat_id"])
        assert saved is not None and session.combat_state is not None
        totals = {host: host_roll + 2 + bonus * (host == candidate), ally: ally_roll + 2 + bonus * (ally == candidate)}
        expected_party = sorted(world.ids, key=totals.__getitem__, reverse=True)
        summary = result["initiative_order"]
        assert saved.initiative_order == session.combat_state.initiative_order == [row["id"] for row in summary]
        for state in (saved, session.combat_state):
            assert {p.id: p.initiative for p in state.participants if p.type == "player"} == totals
        assert saved.initiative_order[:2] == expected_party
        assert {row["id"]: (row["roll"], row["total"]) for row in summary if row["id"] in totals} == {
            host: (host_roll, totals[host]),
            ally: (ally_roll, totals[ally]),
        }
        assert {row["id"]: row["initiative_bonus"] for row in summary if "initiative_bonus" in row} == (
            {candidate: AWARD} if bonus else {}
        )
        [started] = [event for event in published_payloads(room) if event["type"] == "combat_started"]
        assert started["initiative_order"] == summary
        (handoff,) = factory.call_args.kwargs["chat_ctx"].items
        assert (json.dumps(AWARD) in handoff.content[0]) == bool(bonus)
        if not guest and (patron, archetype) == ("valdris", "marshal"):
            assert projection["synergy"] == PROFILE
            defense = projection["sanctuary_defense"]
            assert (defense["clause_id"], defense["clause_name"]) == (CLAUSE, "Lawful Command")
            assert defense["location_id"] == location
            assert defense["is_sanctuary"] is sanctuary
            assert 'initiated_by="enemies"' in defense["activation_hint"]
        else:
            assert "sanctuary_defense" not in projection
    finally:
        if session.combat_state:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)


async def lawful_command(world: SimpleNamespace) -> None:
    await start_at_sanctuary(world, TEMPLE, {"initiated_by": "enemies"}, True, 1)


async def test_enemy_attack_at_temple_earns_lawful_command(world: SimpleNamespace) -> None:
    await lawful_command(world)


@pytest.mark.parametrize(
    "location,initiator,sanctuary,bonus,options",
    [
        pytest.param(GUILD, {"initiated_by": "enemies"}, True, 1, {"guest": True}, id="guild-guest"),
        pytest.param(TEMPLE, {"initiated_by": "party"}, True, 0, {}, id="party"),
        pytest.param(TEMPLE, {}, True, 0, {}, id="omitted"),
        pytest.param(TEMPLE, {"initiated_by": None}, True, 0, {}, id="null"),
        pytest.param(MARKET, {"initiated_by": "enemies"}, False, 0, {}, id="untagged"),
        pytest.param(TEMPLE, {"initiated_by": "enemies"}, False, 0, {"override": False}, id="tag-removed"),
        pytest.param(MARKET, {"initiated_by": "enemies"}, True, 1, {"override": True}, id="tag-added"),
        pytest.param(TEMPLE, {"initiated_by": "enemies"}, True, 0, {"patron": "kaelen"}, id="other-patron"),
        pytest.param(TEMPLE, {"initiated_by": "enemies"}, True, 0, {"archetype": "warrior"}, id="other-class"),
    ],
)
async def test_lawful_command_uses_current_location_and_combat_initiator(
    world: SimpleNamespace, location: str, initiator: dict, sanctuary: bool, bonus: int, options: dict
) -> None:
    await start_at_sanctuary(world, location, initiator, sanctuary, bonus, **options)


SCENARIOS = {CLAUSE: ("patron_synergy_combat:sanctuary_initiative_bonus", lawful_command, [()])}
