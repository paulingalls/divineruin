"""pytest-bdd step defs for the M1.6 companion-errand acceptance scenarios.

Drives the real DispatchAgent (Haiku) + a real Postgres testcontainer via the
LiveKit test framework. Errand tools live in DispatchAgent (story-009); errand
templates come from the shared content/DB source (story-011). Skips entirely
without ANTHROPIC_API_KEY (the pre-sprint-close / test-creation schedule, ADR 0003).

Steps are SYNC and drive async work through the shared per-scenario event loop on
a background thread (the `harness` fixture in conftest.py): pytest-bdd 8.1 does not
await async step functions, so async steps would silently skip their assertions
(decision bdd-async-step-pattern).

The worker-resolution scenario no-ops TTS prerender (synthesize_segments) and the
post-resolution notification/world-news fan-out — those are paid external delivery
steps outside the errand seam. Real LLM narration (generate_activity_narration)
still runs, and the AC ("narration + decision options stored") is satisfied at the
worker's cache-write, which precedes audio prerender.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from acceptance.seeds import clear_async_activities, seed_async_activity, seed_player
from livekit.agents.llm import ChatContext
from livekit.agents.voice import AgentSession
from livekit.plugins import anthropic
from pytest_bdd import given, parsers, scenarios, then, when

import db
import db_activity_queries
from dispatch_agent import create_dispatch_agent
from session_data import CompanionState, SessionData

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="LLM acceptance runs require ANTHROPIC_API_KEY (ADR 0003 pre-sprint-close schedule)",
)

# Production gameplay model (agent.py) — acceptance runs at production parity.
_AGENT_MODEL = "claude-haiku-4-5-20251001"

_KAEL = {"id": "companion_kael", "name": "Kael", "relationship_tier": 2}

scenarios("features/m1_6_companion_errands.feature")


# --- Dispatch scenario ---------------------------------------------------------


@given("a player in the dispatch scene with companion Kael and a free companion slot")
def _given_dispatch_scene(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1", location_id="accord_guild_hall", companion=_KAEL)
        await clear_async_activities(pool, "player_1")

        session_data = SessionData(
            player_id="player_1",
            location_id="accord_guild_hall",
            companion=CompanionState(id="companion_kael", name="Kael", session_count=4),
        )
        # Brief the dispatch scene with the ids the DM needs — there is no query
        # tool for errands, so the scene context is the realistic id source. STATE
        # only, no tool instruction, so the assertion still tests the agent's own
        # tool choice.
        ctx = ChatContext()
        ctx.add_message(
            role="system",
            content=(
                "The player is in the dispatch scene with their companion Kael (id companion_kael), "
                "who is present and ready for an errand. Valid scouting destinations right now: "
                "Millhaven (id millhaven), the Greyvale ruins entrance (id greyvale_ruins_entrance), "
                "and the Accord dockside (id accord_dockside)."
            ),
        )
        session = AgentSession(
            llm=anthropic.LLM(model=_AGENT_MODEL, caching="ephemeral"),
            userdata=session_data,
        )
        await session.start(create_dispatch_agent(chat_ctx=ctx))
        harness.state["session"] = session

    harness.run_sync(_setup())


@when(parsers.parse('the player says "{utterance}"'))
def _player_says(harness: SimpleNamespace, utterance: str) -> None:
    session = harness.state["session"]

    async def _run() -> Any:
        return await session.run(user_input=utterance)

    harness.state["result"] = harness.run_sync(_run())


@then(parsers.parse('the agent calls the "{tool_name}" tool'))
def _agent_calls_tool(harness: SimpleNamespace, tool_name: str) -> None:
    harness.state["result"].expect.contains_function_call(name=tool_name)


@then("an in-progress companion errand row exists for the player")
def _errand_row_exists(harness: SimpleNamespace) -> None:
    async def _check() -> list[dict]:
        return await db_activity_queries.get_player_activities("player_1", status="in_progress")

    rows = harness.run_sync(_check())
    errands = [r for r in rows if r.get("activity_type") == "companion_errand"]
    assert len(errands) == 1, f"expected exactly one in-progress companion_errand row, got {rows}"


# --- Worker-resolution scenario ------------------------------------------------


@given("a dispatched companion errand that is due to resolve")
def _given_due_errand(harness: SimpleNamespace) -> None:
    async def _setup() -> None:
        pool = await db.get_pool()
        await seed_player(pool, player_id="player_1", companion=_KAEL)
        await clear_async_activities(pool, "player_1")
        # resolve_at in the past so get_due_activities() picks it up.
        await seed_async_activity(
            pool,
            activity_id="activity_errand01",
            player_id="player_1",
            errand_type="scout",
            destination="millhaven",
            status="in_progress",
            resolve_at="2020-01-01T00:00:00+00:00",
        )
        harness.state["errand_id"] = "activity_errand01"

    harness.run_sync(_setup())


@when("the async worker resolves due activities")
def _worker_resolves(harness: SimpleNamespace) -> None:
    from async_worker import resolve_due_activities

    async def _run() -> int:
        return await resolve_due_activities()

    # No-op TTS prerender + the post-resolution notification/world-news fan-out —
    # paid external delivery outside the errand seam. The stored outcome (the AC
    # target) is written before any of these.
    with (
        patch("async_worker.synthesize_segments", new_callable=AsyncMock, return_value="activity_errand01.mp3"),
        patch("async_worker.generate_world_news", new_callable=AsyncMock),
        patch("async_worker.generate_notification_hook", new_callable=AsyncMock, return_value="Kael returns."),
        patch("async_worker.send_push_notification", new_callable=AsyncMock),
    ):
        harness.state["resolved_count"] = harness.run_sync(_run())


@then("the errand's stored outcome carries narration and decision options")
def _outcome_stored(harness: SimpleNamespace) -> None:
    async def _read() -> dict | None:
        return await db_activity_queries.get_activity(harness.state["errand_id"])

    assert harness.state["resolved_count"] >= 1
    row = harness.run_sync(_read())
    assert row is not None
    outcome = row.get("outcome")
    assert outcome is not None, "worker did not persist an outcome"
    assert outcome.get("narrative_context"), "outcome missing narrative_context"
    assert row.get("decision_options"), "no decision options stored for the Catch-Up feed"
    assert row.get("narration_text"), "no narration text stored"
