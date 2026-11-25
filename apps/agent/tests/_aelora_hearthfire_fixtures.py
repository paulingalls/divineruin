from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from _mortaen_threshold_fixtures import FOE, active, events, fight
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import game_tools
from livekit.agents.llm import ToolError
from test_patron_engine_valdris import checkpoint
from voice_condition_fixtures import participant

import db_mutations
from combat_agent import CombatAgent
from combat_participant import CombatParticipant
from dice import DiceResult
from session_data import CompanionState

GIFT = "aelora_hearthfire"
COMPANION = "companion_kael"
OTHER_GIFTS = {"aelora_community_shield": {"spent": True}}


def point(x: float, z: float = 0) -> dict:
    return {"x": x, "y": 0, "z": z}


@asynccontextmanager
async def hearth(world: SimpleNamespace, *, patron: str = "aelora", favor: int = 75) -> AsyncIterator[Any]:
    async with fight(
        world, patron=patron, favor=favor, guest="zhael", guest_favor=75, hp=98, guest_hp=30, gifts=OTHER_GIFTS
    ):
        session = world.ctx.userdata
        state = active(world)
        owner, guest = world.ids
        session.companion = CompanionState(id=COMPANION, name="Kael")
        state.participants.append(CombatParticipant(COMPANION, "Kael", "companion", 1, 10, 100, 10))
        state.initiative_order.append(COMPANION)
        state.spatial["positions"].update(
            {owner: point(5), guest: point(5, 15), COMPANION: point(6), FOE: point(-8), "mawling_2": point(40)}
        )
        state.spatial["speeds"][COMPANION] = 30
        participant(state, FOE).hp_current = 1
        await checkpoint(world)
        yield game_tools(session, agent=CombatAgent())


async def snapshot(world: SimpleNamespace) -> tuple:
    state = active(world)
    live = state.to_dict() if state else None
    saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool) if state else None
    assert live == (saved.to_dict() if saved else None)
    return await row(world, 0), await row(world, 1), live, events(world)


async def refuse(world: SimpleNamespace, call: Any, reason: str) -> None:
    before = await snapshot(world)
    with pytest.raises(ToolError, match=reason):
        await call("activate", id=GIFT)
    assert await snapshot(world) == before


@contextmanager
def healing_rolls(*faces: int) -> Iterator[Any]:
    with patch("dice.roll", side_effect=[DiceResult("1d6", [face], [], face) for face in faces]) as dice:
        yield dice


async def fall(world: SimpleNamespace, index: int, failures: int = 1) -> None:
    pid = world.ids[index]
    target = participant(active(world), pid)
    target.hp_current = 0
    target.is_fallen = True
    target.death_save_successes = int(failures < 3)
    target.death_save_failures = failures
    await db_mutations.update_player_hp(pid, 0, conn=world.pool)


def move(actor_id: str, x: float) -> dict:
    return {"reshape": [], "movement_mode": "ground", "kind": "move", "actor_id": actor_id, "destination": point(x)}
