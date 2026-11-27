"""Refusals and atomic commit of Wild Shape."""

from unittest.mock import AsyncMock

import pytest
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_wild_shape import (
    ABILITY,
    SPELL,
    declare,
    enter,
    prepare,
    updates,
)
from acceptance.test_wild_shape import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_wild_shape import (
    walk as walk,
)

import ability_persistence
import db_mutations
import db_queries


@pytest.mark.parametrize(
    ("level", "form", "targets", "reason"),
    [
        (5, "dire_bear", [], "level 10"),
        (4, "grey_wolf", [], "level 5"),
        (5, "missing_beast", [], "missing_beast"),
        (5, "", [], "form id"),
        (5, "grey_wolf", ["bandit_1"], "only the caster"),
        (5, "grey_wolf", ["bandit_1", "bandit_2"], "only the caster"),
    ],
)
async def test_invalid_selection(walk: MawlingHarness, level: int, form: str, targets: list[str], reason: str) -> None:
    await prepare(walk, "druid", level)
    await enter(walk)
    before, events = await walk.snapshot(), updates(walk)
    result = await walk.command(
        "declare_phase",
        {
            "declarations": [
                {
                    "kind": "ability",
                    "actor_id": walk.players[0],
                    "action": ABILITY,
                    "targets": targets,
                    "argument_type": form,
                    "reshape": [],
                }
            ]
        },
        error=True,
    )
    assert await walk.snapshot() == before
    assert updates(walk) == events
    assert reason in result.lower()


@pytest.mark.parametrize("archetype", ["druid", "warden"])
@pytest.mark.parametrize("reason", ["focus", "stamina", "already in"])
async def test_ineligible_caster(walk: MawlingHarness, archetype: str, reason: str) -> None:
    pid = await prepare(
        walk,
        archetype,
        level=20 if archetype == "warden" and reason == "already in" else 5,
        focus=3 if reason == "focus" else 4,
        stamina=2 if reason == "stamina" else 3,
    )
    await enter(walk)
    action = ABILITY if archetype == "druid" else SPELL
    form = "grey_wolf" if archetype == "druid" else "steppe_bison"
    if reason == "already in":
        await declare(walk, action, form)
        await walk.drain()
        await ability_persistence.update_player_resources(pid, focus=4, stamina=3, conn=walk.pool)
    before, players = await walk.snapshot()
    if reason == "already in":
        message = await declare(walk, action, "wild_boar", error=True)
    else:
        await declare(walk, action, form)
        message = await walk.command("resolve_phase", {}, error=True)
    after, actual_players = await walk.snapshot()
    assert actual_players == players
    assert after["participants"] == before["participants"]
    assert reason in message.lower()


@pytest.mark.parametrize("archetype", ["druid", "warden"])
async def test_failed_save_rolls_back_form_and_costs(
    walk: MawlingHarness, monkeypatch: pytest.MonkeyPatch, archetype: str
) -> None:
    pid = await prepare(walk, archetype)
    await enter(walk)
    await declare(walk, ABILITY if archetype == "druid" else SPELL, "grey_wolf")
    before, events = await walk.snapshot(), updates(walk)
    failure = AsyncMock(side_effect=RuntimeError("wild shape save fault"))
    with monkeypatch.context() as patch:
        patch.setattr(db_mutations, "save_combat_state", failure)
        assert "internal error" in await walk.command("resolve_phase", {}, error=True)
    failure.assert_awaited_once()
    assert await walk.snapshot() == before
    assert updates(walk) == events
    await walk.drain()
    row = await db_queries.get_player(pid)
    assert row is not None
    assert (row["focus"]["current"], row["stamina"]["current"]) == (0, 0)
    saved = (await walk.reload()).get_participant(pid)
    assert saved is not None and saved.wild_shape is not None
    assert saved.wild_shape["form_id"] == "grey_wolf"
    original = next(p for p in before[0]["participants"] if p["id"] == pid)
    assert saved.wild_shape["original_action_pool"] == original["action_pool"]
    assert [action["name"] for action in saved.action_pool] == ["Bite"]
