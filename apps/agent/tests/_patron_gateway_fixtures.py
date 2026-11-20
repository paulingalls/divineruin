import json
from copy import deepcopy

from _patron_engine_fixtures import configure
from _zhael_fate_fixtures import game_tools
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import still_charm
from exploration_agent import ExplorationAgent
from session_data import CompanionState

GIFT = "nythera_beyond_the_horizon"
MARKET = "accord_market_square"
MILL = "millhaven"
WILDERNESS = "greyvale_wilderness_north"
HALL = "accord_training_hall"


async def prepare(world, *, favor=75, follower_index=1):
    session = world.ctx.userdata
    host, follower = world.ids[1 - follower_index], world.ids[follower_index]
    for index, pid in enumerate(world.ids):
        is_follower = index == follower_index
        await seed_player_with_pools(world.pool, player_id=pid)
        await configure(
            world,
            "nythera" if is_follower else "veythar",
            "seeker" if is_follower else "mage",
            index=index,
            divine_favor={"patron": "nythera" if is_follower else "veythar", "level": favor, "max": 100},
            name="Follower" if is_follower else "Host",
            location_id=MARKET,
            travel_state={"destination": HALL},
            resonance={"current": 9 if is_follower else 3, "flickering_bonus": 2 if is_follower else 0},
            patron_gifts={"unrelated": {"spent": True}},
        )
    session.location_id = MARKET
    session.companion = CompanionState(id="companion_kael", name="Kael")
    session.member_state(host).resonance.current = 3
    session.member_state(follower).resonance.current = 1
    lifecycle = _live_party(session, host, follower)
    for pid in world.ids:
        assert await lifecycle.authorize(pid) is not None
    session.event_bus.drain()
    await visit(world, follower, MARKET, MILL)
    await visit(world, host, HALL)
    return ExplorationAgent(initial_location=MARKET)


async def visit(world, player_id, *locations):
    await world.pool.executemany(
        "INSERT INTO player_map_progress (player_id, location_id, data) VALUES ($1,$2,'{}')",
        [(player_id, location) for location in locations],
    )


async def call(world, agent, name="activate", *, actor=None, **args):
    session = world.ctx.userdata
    actor = actor or world.ids[1]
    lifecycle = session.multiplayer_owner.lifecycle
    generation = lifecycle.current_generation(actor)
    assert generation is not None
    with session._bind_authenticated_actor(actor, generation, lifecycle.require_authorized):
        return await game_tools(session, agent=agent)(name, **args)


async def cross(world, agent, destination=MILL, *, actor=None):
    return await call(
        world, agent, actor=actor, id=GIFT, **({"target_id": destination} if destination is not None else {})
    )


async def offer(world, agent):
    patron = await call(world, agent, "query_info", kind="patron")
    return next(row for row in patron["abilities"] if row["id"] == GIFT)


async def party_rows(world, *, conn=None):
    rows = await (conn or world.pool).fetch("SELECT player_id, data FROM players WHERE player_id = ANY($1)", world.ids)
    return {r["player_id"]: json.loads(r["data"]) for r in rows}


async def snapshot(world, agent):
    session = world.ctx.userdata
    progress = await world.pool.fetch(
        "SELECT * FROM player_map_progress WHERE player_id = ANY($1) ORDER BY player_id, location_id", world.ids
    )
    return deepcopy(
        (
            await party_rows(world),
            [dict(r) for r in progress],
            session.location_id,
            session.location_ward,
            session.session_locations_visited,
            session.player_summary_metrics,
            session.companion.session_memories,
            [session.member_state(pid) for pid in world.ids],
            session.combat_state.to_dict() if session.combat_state else None,
            agent._agent_type if isinstance(agent, ExplorationAgent) else None,
            published_payloads(session.room),
            session.event_bus.qsize,
        )
    )


async def charm(world, pid, *, conn=None):
    flags = {
        still_charm.key(MARKET): json.dumps(
            {
                "location_id": MARKET,
                "kind": still_charm.PARADISE_TRAP,
                "remaining_zone_hours": None,
            }
        )
    }
    await (conn or world.pool).execute(
        "UPDATE players SET data = jsonb_set(data, '{flags}', $2::jsonb) WHERE player_id = $1",
        pid,
        json.dumps(flags),
    )
