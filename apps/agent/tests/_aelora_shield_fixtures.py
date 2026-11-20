from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import asyncpg
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import encounter
from _zhael_fate_fixtures import defend, game_tools
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import place_actors

import db_mutations
import db_queries
from combat_agent import CombatAgent
from exploration_agent import ExplorationAgent

SHIELD = "aelora_community_shield"
SPENT = {"spent": True}
OTHER_GIFTS = {"aelora_hearthfire": SPENT}
NAMES = ("Mira", "Tovin")
ToolCall = Callable[..., Coroutine[object, object, dict]]


@asynccontextmanager
async def shield_setup(
    world: SimpleNamespace,
    *,
    combat: bool = False,
    pool: int = 0,
    level: int = 6,
    charisma: int = 16,
    queued: bool = False,
    case: str = "",
    patron: str = "aelora",
    favor: int = 40,
) -> AsyncIterator[ToolCall]:
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    actor, target = world.ids
    for index, pid in enumerate(world.ids):
        await seed_player_with_pools(world.pool, player_id=pid, class_="mage", focus_current=3 + index)
        await configure(
            world,
            patron if index == 0 else "veythar",
            "mage",
            index=index,
            name=NAMES[index],
            level=level if index == 0 else 15,
            attributes={"charisma": charisma if index == 0 else 20},
            divine_favor={"patron": patron if index == 0 else "veythar", "level": favor, "max": 100},
            hp={"current": 17 + index, "max": 20},
            temp_hp=pool if index == 1 else 0,
            patron_gifts=OTHER_GIFTS if index == 0 else {},
            location_id=session.location_id,
        )
    lifecycle = _live_party(session, actor) if case == "departed" else _live_party(session, actor, target)
    state = None
    try:
        if combat:
            encounter(world)
            state = place_actors(session.combat_state)
            state.combat_id = actor
            state.initiative_order = list(state.initiative_order)
            state.spatial["positions"][target]["x"] = 120
            ally = state.participants[1]
            for index, participant in enumerate(state.participants):
                participant.name = NAMES[index]
                participant.hp_current = 17 + index
            ally.temp_hp = pool
            if queued:
                state.current_turn_index = 1
                state.beat = "resolution"
                state.pending_declarations[actor] = defend(actor)
            await save_checkpoint(world)
        generation = await lifecycle.authorize(actor)
        assert generation
        with session._bind_authenticated_actor(actor, generation, lifecycle.require_authorized):
            yield game_tools(session, agent=CombatAgent() if combat else ExplorationAgent())
    finally:
        await lifecycle.aclose()
        if state is not None:
            await db_mutations.delete_combat_state(state.combat_id, conn=world.pool)


async def save_checkpoint(world: SimpleNamespace) -> None:
    state = world.ctx.userdata.combat_state
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)


async def checkpoint(world: SimpleNamespace, *, conn: asyncpg.Connection | None = None) -> dict | None:
    state = world.ctx.userdata.combat_state
    if state is None:
        return None
    saved = await db_mutations.load_combat_state(state.combat_id, conn=conn or world.pool)
    assert saved is not None
    return saved.to_dict()


async def snapshot(world: SimpleNamespace) -> tuple[list[dict | None], dict | None, dict | None, list[dict]]:
    session = world.ctx.userdata
    return (
        [await db_queries.get_player(pid, conn=world.pool) for pid in world.ids],
        deepcopy(session.combat_state.to_dict()) if session.in_combat else None,
        await checkpoint(world),
        published_payloads(session.room),
    )


async def shield_status(call: ToolCall) -> dict:
    return next(gift for gift in (await call("query_info", kind="patron"))["abilities"] if gift["id"] == SHIELD)
