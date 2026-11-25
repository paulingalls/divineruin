from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import MagicMock, patch

import pytest
from _mortaen_threshold_fixtures import active, declare, reload_state
from _patron_engine_fixtures import configure
from _thyra_wrath_fixtures import checkpoint, fighter, snapshot
from _thyra_wrath_fixtures import fight as patron_fight
from _zhael_fate_fixtures import attack
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from voice_condition_fixtures import participant

from dice import DiceResult

GIFT = "valdris_the_scales_verdict"
FOE = "raider"
STRIKE = {
    "name": "Radiant Test Strike",
    "kind": "attack",
    "damage": "1d4",
    "damage_type": "force",
    "type": "ranged",
    "reach": 30,
    "attack_bonus": 5,
}


@asynccontextmanager
async def fight(world, *foes, **options):
    if not foes and "encounter" not in options:
        foes = (fighter(FOE, action_pool=[STRIKE.copy()]),)
    options.setdefault("patron", "valdris")
    async with patron_fight(world, *foes, **options) as call:
        yield call


@contextmanager
def verdict_roll(notation: str = "2d8") -> Iterator[MagicMock]:
    faces = [3, 4] if notation == "2d8" else [3, 4, 5, 6]
    with patch("dice.roll", return_value=DiceResult(notation, faces, [], sum(faces))) as roll:
        yield roll


async def activate(call, target=FOE, *, notation="2d8"):
    with (
        verdict_roll(notation) as roll,
        patch("check_resolution.dice_roll", side_effect=AssertionError("Verdict requires no attack or save")),
    ):
        result = await call("activate", id=GIFT, target_id=target)
    roll.assert_called_once_with(notation)
    return result


async def refuse(world, call, reason: str, **selectors) -> None:
    before = await snapshot(world)
    with verdict_roll() as roll, pytest.raises(ToolError, match=reason):
        await call("activate", id=GIFT, **selectors)
    roll.assert_not_called()
    assert await snapshot(world) == before


async def queue_strike(world, call, victim: str, foe: str = FOE, action=STRIKE["name"]) -> None:
    await declare(world, call, {**attack(foe, victim), "action": action})


async def advance(world, call, beat: str, *, face: int = 15) -> list[dict]:
    packets = []
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        for _ in range(8):
            result = await call("resolve_phase")
            packets.extend(result["packets"])
            if result["beat"] == beat:
                await reload_state(world)
                return packets
    raise AssertionError(f"Combat did not reach {beat}")


async def set_health(world, hp: int, temp_hp: int = 0, *, gifts: dict | None = None) -> None:
    actor = participant(active(world), world.ids[0])
    actor.hp_current, actor.hp_max, actor.temp_hp = hp, 20, temp_hp
    await configure(
        world,
        "valdris",
        "warrior",
        divine_favor={"patron": "valdris", "level": 75, "max": 100},
        hp={"current": hp, "max": 20},
        temp_hp=temp_hp,
        patron_gifts=gifts or {},
    )
    await checkpoint(world)


def omit_participant(state, participant_id: str) -> None:
    state.participants.remove(participant(state, participant_id))
    state.initiative_order.remove(participant_id)
    del state.spatial["positions"][participant_id]
    del state.spatial["speeds"][participant_id]
