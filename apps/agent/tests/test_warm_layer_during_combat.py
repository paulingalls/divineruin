"""The warm layer does not MOVE during a fight — the fight rides the hot layer instead.

Injecting the warm layer rewrites the system prompt, and the anthropic plugin caches on the
last system block: a per-round rewrite invalidates the prefix AND the whole message history
behind it. So the combat block left the warm layer entirely (story-024, debt ce06dd8c) and
the guards here pin what remains — a system prompt that stands still across a fight, and
story-023's OTHER warm sections still refreshing across the handoff.

The prompt tests drive the event handler DIRECTLY (`_process_events`), never the 30s bus
fallback: `_run`'s timed-out branch rebuilds unconditionally, so a test that let the timer
fire would go green against the timer and not against the fix.

`TestProcessSurvivesTheHandoff` is the exception and drives the LIVE loop, because what it
guards is the loop still being alive after the handoff into combat — a stopped process can
still be driven by hand.
"""

import ast
import asyncio
import pathlib
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from prompt_fixtures import SAMPLE_LOCATION, SAMPLE_QUEST, sample_combat_state

import background_process
import event_types as E
from background_process import BackgroundProcess
from combat_agent import CombatAgent
from event_bus import GameEvent
from exploration_agent import ExplorationAgent
from session_data import CombatParticipant, CombatState, SessionData
from system_prompts import COMBAT_SYSTEM_PROMPT

DB_SEAMS = (
    "background_process.db_queries.get_active_player_quests",
    "background_process.db_content_queries.get_location",
    "background_process.db_queries.get_npcs_at_location",
    "background_process.db_training.get_player_training_activities",
)


@contextmanager
def _mock_db():
    """The four DB seams _rebuild_warm_layer fans out to."""
    with (
        patch(DB_SEAMS[0], new_callable=AsyncMock, return_value=[]) as quests,
        patch(DB_SEAMS[1], new_callable=AsyncMock, return_value=SAMPLE_LOCATION) as location,
        patch(DB_SEAMS[2], new_callable=AsyncMock, return_value=[]) as npcs,
        patch(DB_SEAMS[3], new_callable=AsyncMock, return_value=[]) as training,
    ):
        yield (quests, location, npcs, training)


def _participant(combat_state: CombatState, pid: str) -> CombatParticipant:
    p = combat_state.get_participant(pid)
    assert p is not None
    return p


def _make_bg(combat_state: CombatState | None = None) -> tuple[BackgroundProcess, MagicMock]:
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall")
    sd.combat_state = combat_state
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    # The process composes the CURRENT agent's static half, so a mock target must answer with
    # a real string (a MagicMock would not join).
    agent.static_prompt = MagicMock(return_value="STATIC")
    session = MagicMock()
    session.current_agent = agent
    return BackgroundProcess(session=session, session_data=sd), agent


def _ui_update() -> list[GameEvent]:
    return [GameEvent(event_type=E.COMBAT_UI_UPDATE, payload={})]


def _last_warm(agent: MagicMock) -> str:
    return agent.update_instructions.await_args[0][0]


def _is_running(bg: BackgroundProcess) -> bool:
    return bg._task is not None and not bg._task.done()


async def _settle(predicate, what: str) -> None:
    """Yield to the running loop until it has done its work — fail loud, never silently pass.

    No timer is advanced and no fallback can fire: the loop is woken by the event we published,
    and each iteration here is a bare event-loop turn.
    """
    for _ in range(50):
        await asyncio.sleep(0)
        if predicate():
            return
    raise AssertionError(f"background process never {what}")


@contextmanager
def _mock_startup_db():
    """Everything `_run` touches before it parks on the bus: the rider-scene prefetch plus the
    four warm-layer queries."""
    with (
        patch("background_process.db_content_queries.get_scene", new_callable=AsyncMock, return_value=None),
        _mock_db() as seams,
    ):
        yield seams


async def _enter_exploration(session: MagicMock, sd: SessionData) -> ExplorationAgent:
    agent = ExplorationAgent()
    session.current_agent = agent
    with (
        patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
        patch("exploration_agent.start_specialization_tap"),
        # Sync mock + no-op fire_and_forget: the real method is async, so an unawaited
        # AsyncMock coroutine would leak.
        patch.object(agent, "_publish_session_init", new_callable=MagicMock),
        patch.object(agent, "_fire_and_forget"),
    ):
        await agent.on_enter()
    return agent


async def _exit_exploration(agent: ExplorationAgent, session: MagicMock) -> None:
    """What LiveKit runs on the handoff INTO combat: AgentActivity.drain awaits on_exit."""
    with (
        patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)),
        patch("exploration_agent.generate_session_summary", new_callable=AsyncMock, return_value={}),
        patch("exploration_agent.publish_game_event", new_callable=AsyncMock),
        patch("exploration_agent.db_mutations.save_session_summary", new_callable=AsyncMock),
    ):
        await agent.on_exit()


class TestProcessSurvivesTheHandoff:
    """AC4: the OTHER warm sections still refresh across the handoff, and combat is not one.

    Story-023's value, unchanged — quests, location, NPCs and corruption keep reaching whichever
    agent holds the floor. What story-024 removes is the ACTIVE COMBAT block, so this drives the
    live loop with a REBUILD event (a quest advancing) while a real fight is underway.
    """

    async def test_the_running_loop_updates_the_combat_agent_mid_fight(self):
        """Driven through the live loop, not `_process_events`: a stopped process can still be
        driven by hand, so only the loop can red when the handoff kills it."""
        sd = SessionData(player_id="p1", location_id="accord_guild_hall", room=MagicMock())
        session = MagicMock()
        session.userdata = sd

        with _mock_startup_db() as (quests, _location, _npcs, _training):
            exploration = await _enter_exploration(session, sd)
            bg = sd.background
            assert bg is not None
            await _settle(lambda: bg._last_warm_layer != "", "built its initial warm layer")

            await _exit_exploration(exploration, session)

            combat = CombatAgent()
            session.current_agent = combat
            # A LIVE fight, so "no ACTIVE COMBAT block" below cannot pass vacuously.
            sd.combat_state = sample_combat_state(round_number=2, hp_current=8)
            try:
                quests.return_value = [SAMPLE_QUEST]
                sd.event_bus.publish(
                    GameEvent(
                        event_type=E.QUEST_UPDATED,
                        payload={"quest_name": SAMPLE_QUEST["quest_name"], "objective": "Find the source."},
                    )
                )
                await _settle(lambda: SAMPLE_QUEST["quest_name"] in combat.instructions, "reached the combat agent")

                assert _is_running(bg)
                warm = str(combat.instructions)
                assert "Find the source of the anomaly." in warm  # the quest section refreshed
                assert SAMPLE_LOCATION["name"] in warm  # and the location section is still there
                assert "ACTIVE COMBAT" not in warm  # but the fight never enters the warm layer
                # The static half is the CURRENT agent's own: composing the exploration prompt
                # here would silently replace COMBAT_SYSTEM_PROMPT mid-fight.
                assert warm.startswith(COMBAT_SYSTEM_PROMPT)
                assert "The player is currently at location ID" not in warm
            finally:
                await bg.stop()


class TestStartedOnceForTheSession:
    """The other half of session ownership: one loop, and only on the gameplay path."""

    async def test_a_handback_does_not_start_a_second_loop(self):
        """`end_combat` hands back a NEW ExplorationAgent over the same SessionData, and no
        agent stops the loop any more — so `on_enter` is the only place that can refuse the
        second one. Two loops split this queue-backed bus between them and rebuild twice on
        every fallback."""
        sd = SessionData(player_id="p1", location_id="accord_guild_hall", room=MagicMock())
        session = MagicMock()
        session.userdata = sd

        with _mock_startup_db():
            await _enter_exploration(session, sd)
            first = sd.background
            assert first is not None
            await _settle(lambda: first._last_warm_layer != "", "built its initial warm layer")

            try:
                await _enter_exploration(session, sd)
                assert sd.background is first
                assert _is_running(first)
            finally:
                await first.stop()

    def test_the_gameplay_path_is_the_only_construction_site(self):
        """AC: a prologue or onboarding session constructs NO background process.

        Structural because that is where the fault injection the card names lives — building
        one on `agent.py`'s prologue branch. Driving `PrologueAgent.on_enter` would stay green
        through exactly that change, and the prologue/onboarding warm layer has no combat, no
        quests and no companion to render.
        """
        agent_dir = pathlib.Path(background_process.__file__).parent  # cwd-independent
        sources = sorted(p for p in agent_dir.glob("*.py") if p.name != "background_process.py")
        built_in = {
            path.name
            for path in sources
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "BackgroundProcess"
        }
        assert built_in == {"exploration_agent.py"}


# The per-round warm-refresh path, by name. Source text and not AST: "gone from the tree, not
# left dormant behind a flag" includes a commented-out body, which an AST walk cannot see.
DELETED_REFRESH_PATH = (
    "format_combat_section",
    "_refresh_combat_section",
    "needs_combat_refresh",
    "COMBAT_REFRESH_EVENT_TYPES",
    "compose_warm_layer",
)


class TestTheRefreshPathIsGone:
    def test_no_agent_module_still_names_it(self):
        """AC5: the trigger that rewrote the system prompt every round is deleted, not disabled.

        Top-level modules only — `tests/` is not matched by the glob, so this file may name
        the strings freely.
        """
        agent_dir = pathlib.Path(background_process.__file__).parent  # cwd-independent
        survivors = {
            (path.name, name)
            for path in agent_dir.glob("*.py")
            for name in DELETED_REFRESH_PATH
            if name in path.read_text()
        }
        assert survivors == set()


class TestTheSystemPromptDoesNotMoveDuringAFight:
    async def test_three_rounds_move_the_system_prompt_zero_times(self):
        """AC1: the prefix is written at the handoff and never again while the fight runs."""
        cs = sample_combat_state(round_number=1)
        bg, agent = _make_bg(cs)
        with _mock_db():
            await bg._rebuild_warm_layer()
            at_handoff = bg._last_warm_layer
            assert at_handoff, "nothing was ever composed — the counts below would be vacuous"
            agent.update_instructions.reset_mock()

            for round_number in (2, 3, 4):
                cs.round_number = round_number
                _participant(cs, "grosh").hp_current = 20 - 4 * round_number
                await bg._process_events(_ui_update(), timed_out=False)

            assert agent.update_instructions.await_count == 0

            # Byte-identical from the handoff into combat until the handback: a rebuild forced
            # after three rounds of mutated combat state composes the same string, so it does
            # not reach the agent either. Reds the moment combat data leaks back in.
            await bg._rebuild_warm_layer()

        assert bg._last_warm_layer == at_handoff
        assert agent.update_instructions.await_count == 0
