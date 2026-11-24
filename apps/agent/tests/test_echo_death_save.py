"""Destroyed Hollowed echoes stay down through phase wrap and death saves."""

from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from test_encounter_facts_damage import GOBLIN, OTHER, Fight, dice, fight, goblin_strike
from voice_condition_fixtures import participant

import db_mutations
from combat_death_save import request_death_save
from combat_turn import declare_phase, resolve_phase

ToolCall = Callable[..., Awaitable[Any]]
DestroyedEcho = tuple[Fight, ToolCall, dict]


async def advance(f: Fight, call: ToolCall, strike: dict | None = None) -> dict:
    state = f.session.combat_state
    declarations = [strike] if strike else []
    for pid in state.initiative_order:
        actor = participant(state, pid)
        if not (actor.is_fallen or actor.is_dead) and (strike is None or pid != strike["actor_id"]):
            declarations.append(defend(pid))
    await call("declare_phase", declarations=declarations)
    with dice(*((15,) if strike else ())):
        for _ in range(5):
            result = await call("resolve_phase")
            if isinstance(result, tuple):
                return result[1]
            if result["beat"] == "declaration":
                await f.reload()
                return result
    raise AssertionError("phase did not wrap")


@pytest.fixture
async def destroyed_echo(world: SimpleNamespace) -> AsyncIterator[DestroyedEcho]:
    async with fight(world, "thyra", hollowed=True) as f:
        state = f.session.combat_state
        hero = participant(state, f.hero)
        hero.hp_current = 5
        attributes = {"strength": 14, "charisma": 8, "constitution": 13}
        await configure(
            world, "thyra", "warrior", hp={"current": hero.hp_current, "max": hero.hp_max}, attributes=attributes
        )
        ally = participant(state, f.ally)
        ally.name = "Sable"
        await configure(world, "thyra", "warrior", index=1, conditions=ally.conditions, attributes=attributes)

        call = game_tools(f.session, declare_phase, resolve_phase, request_death_save)
        await advance(f, call, goblin_strike(GOBLIN, f.ally))
        echo = participant(f.session.combat_state, f.ally)
        assert (echo.type, echo.hp_current, echo.is_fallen) == ("temporary_hollowed", 10, False)

        await advance(f, call, attack(f.hero, f.ally))
        wrap = await advance(f, call, attack(f.hero, f.ally))
        state = f.session.combat_state
        echo = participant(state, f.ally)
        assert (echo.type, echo.hp_current, echo.is_fallen, echo.is_dead) == ("temporary_hollowed", 0, True, False)
        assert all(not participant(state, pid).is_fallen for pid in (f.hero, GOBLIN, OTHER))
        yield f, call, wrap


async def test_wrap_omits_destroyed_echo(destroyed_echo: DestroyedEcho) -> None:
    _, _, wrap = destroyed_echo
    assert wrap["death_saves_due"] == []


async def test_named_destroyed_echo_cannot_roll(destroyed_echo: DestroyedEcho) -> None:
    f, call, _ = destroyed_echo
    with patch("combat_resolution.dice_roll", return_value=_d20(20)) as die:
        with pytest.raises(ToolError, match=r"Sable.*do not roll"):
            await call("request_death_save", player_id=f.ally)
        die.assert_not_called()


async def test_unnamed_save_ignores_destroyed_echo(destroyed_echo: DestroyedEcho) -> None:
    _, call, _ = destroyed_echo
    with patch("combat_resolution.dice_roll", return_value=_d20(20)) as die:
        with pytest.raises(ToolError, match="No one has fallen"):
            await call("request_death_save")
        die.assert_not_called()


async def test_hero_rolls_then_defeat_settles_both_lives(world: SimpleNamespace, destroyed_echo: DestroyedEcho) -> None:
    f, call, _ = destroyed_echo
    wrap = await advance(f, call, goblin_strike(GOBLIN, f.hero))
    assert wrap["death_saves_due"] == [f.hero]
    state = f.session.combat_state
    hero = participant(state, f.hero)
    assert hero.is_fallen and not hero.is_dead
    echo_before = participant(state, f.ally)

    with patch("combat_resolution.dice_roll", side_effect=[_d20(5), _d20(1)]):
        save = await call("request_death_save")
        assert not save["success"] and save["total_failures"] == 1
        state = await f.reload()
        assert participant(state, f.hero).death_save_failures == 1
        assert participant(state, f.ally) == echo_before

        save = await call("request_death_save")
        assert save["dead"] and save["total_failures"] == 3

    assert (await advance(f, call))["outcome"] == "defeat"
    assert f.session.combat_state is None
    assert await db_mutations.load_combat_state(f.combat_id) is None
    for index in (0, 1):
        player = await row(world, index)
        assert player["death_history"]["count"] == 1
        assert player["hp"]["current"] == player["hp"]["max"] > 0
