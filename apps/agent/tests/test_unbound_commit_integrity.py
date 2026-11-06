"""Fault injection at action commits and their first fallible publication."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _unbound_path_fixtures import cast, encounter, phase, push, row
from _unbound_path_fixtures import world as world
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads


@pytest.mark.parametrize("action", ["push", "cast", "phase"])
async def test_rollback_preserves_resources_memory_uses_and_events(world, action):
    w = world
    if action != "cast":
        encounter(w)
    before = await row(w)
    member = w.ctx.userdata.party.members[1]

    @asynccontextmanager
    async def failing_transaction():
        async with w.db.transaction() as conn:
            yield conn
            raise RuntimeError("injected before commit")

    async def run(database):
        if action == "push":
            return await push(w, database=database)
        if action == "phase":
            return await phase(w, database=database, declare=w.ctx.userdata.combat_state.beat == "declaration")
        return await cast(w, sid="arcane_fireball", database=database)

    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        # Declare publishes no client event; the action's events stay deferred.
        with pytest.raises(RuntimeError, match="before commit"):
            await run(SimpleNamespace(transaction=failing_transaction))
        assert await row(w) == before
        assert member.resonance.current == 9
        assert not member.unbound_raw_channeling_used and not member.unbound_veil_mastery_used
        assert not published_payloads(w.ctx.userdata.room)
        await run(w.db)
        if action == "push":
            with pytest.raises(ToolError, match="spent"):
                await push(w)
        else:
            assert member.unbound_veil_mastery_used
            w.ctx.userdata.combat_state = None
            assert (await cast(w))["hollow_echo"]["band"] == "breach"


@pytest.mark.parametrize("combat", [False, True])
async def test_publish_failure_cannot_restore_committed_mastery(world, combat):
    w = world
    if combat:
        encounter(w)
    echo = MagicMock(publish_hollow_echo=AsyncMock())
    with w.ctx.userdata._bind_authenticated_actor(w.ids[1], 4, lambda *_: None):
        with patch("game_events.publish_game_event", AsyncMock(side_effect=RuntimeError("publisher down"))):
            if combat:
                # EventSink's publisher is imported by value; fail its first post-commit event.
                with patch("combat_events.publish_game_event", AsyncMock(side_effect=RuntimeError("publisher down"))):
                    await phase(w, echo=echo)
            else:
                with patch(
                    "resonance_events.publish_game_event", AsyncMock(side_effect=RuntimeError("publisher down"))
                ):
                    with pytest.raises(RuntimeError, match="publisher down"):
                        await cast(w, sid="arcane_fireball", echo=echo)
        assert w.ctx.userdata.party.members[1].unbound_veil_mastery_used
        assert (await row(w))["focus"]["current"] < 100
        w.ctx.userdata.combat_state = None
        assert (await cast(w))["hollow_echo"]["band"] == "breach"
