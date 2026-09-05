"""The warm layer's ACTIVE COMBAT block tracks the fight it describes.

The refresh tests drive the event handler DIRECTLY (`_process_events`), never the 30s bus
fallback: `_run`'s timed-out branch rebuilds unconditionally, so a test that let the timer
fire would go green against the timer and not against the fix.

`TestProcessSurvivesTheHandoff` is the exception and drives the LIVE loop, because what it
guards is the loop still being alive after the handoff into combat — a stopped process can
still be driven by hand.
"""

import ast
import asyncio
import pathlib
import re
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from prompt_fixtures import SAMPLE_LOCATION, sample_combat_state

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


class TestCombatUiUpdateRefresh:
    async def test_round_and_hp_advance_in_the_warm_layer(self):
        """AC1: a COMBAT_UI_UPDATE driven through the handler re-renders the block."""
        cs = sample_combat_state(round_number=1)
        bg, agent = _make_bg(cs)
        with _mock_db():
            await bg._rebuild_warm_layer()
            assert "Round 1" in _last_warm(agent)

            cs.round_number = 2
            _participant(cs, "grosh").hp_current = 8  # 8/20 -> bloodied
            await bg._process_events(_ui_update(), timed_out=False)

        warm = _last_warm(agent)
        assert "Round 2" in warm
        assert "- Grosh (enemy) — bloodied" in warm
        assert "Round 1" not in warm

    async def test_refresh_before_first_successful_rebuild_is_a_noop(self):
        """A base that was never built is not a base: composing onto it would ship the
        combat block as the agent's ENTIRE warm layer, silently dropping location,
        quests, NPCs, companion and corruption."""
        bg, agent = _make_bg(sample_combat_state(round_number=2))
        await bg._process_events(_ui_update(), timed_out=False)
        assert agent.update_instructions.await_count == 0

    async def test_refresh_issues_no_db_query(self):
        """AC2: the block re-renders from session.combat_state alone.

        Counts awaits rather than raising from a seam: _rebuild_warm_layer wraps its gather
        in `except Exception: return`, so a raising seam would be swallowed and this guard
        would pass while the prompt stayed stale. The round-2 assertion pairs with the counts
        so "refreshed nothing at all" cannot pass either.
        """
        cs = sample_combat_state(round_number=1)
        bg, agent = _make_bg(cs)
        with _mock_db():
            await bg._rebuild_warm_layer()

        cs.round_number = 2
        with _mock_db() as seams:
            # A real str, so that under the naive "just add it to REBUILD_EVENT_TYPES" fix the
            # rebuild COMPLETES and this test reds on the await counts — not on a TypeError from
            # composing a mock.
            with patch("background_process.build_warm_layer", new_callable=AsyncMock) as build:
                build.return_value = "BASE"
                await bg._process_events(_ui_update(), timed_out=False)

        for seam in (*seams, build):
            assert seam.await_count == 0
        assert "Round 2" in _last_warm(agent)


def _round_in(text: str, pattern: str) -> str:
    """The round number a renderer reports — asserting the match so a renderer that stops
    emitting a round at all fails here rather than comparing None to None."""
    match = re.search(pattern, text)
    assert match is not None, f"no round number in: {text}"
    return match.group(1)


def _warm_line_for(warm: str, name: str) -> str:
    """The one ACTIVE COMBAT line for a participant — a whole-block substring check
    passes by accident once a second participant is in the fight."""
    return next(line for line in warm.splitlines() if line.startswith(f"- {name} ("))


class TestWarmAndHotAgree:
    async def test_same_round_and_fallen_state_after_a_refresh(self):
        """AC3: the two renderers of the same fight, compared after a handler-driven refresh."""
        cs = sample_combat_state(round_number=1)
        bg, agent = _make_bg(cs)
        with _mock_db():
            await bg._rebuild_warm_layer()

            cs.round_number = 3
            kael = _participant(cs, "p_kael")
            kael.hp_current = 0
            kael.is_fallen = True
            _participant(cs, "grosh").hp_current = 8
            await bg._process_events(_ui_update(), timed_out=False)

        warm = _last_warm(agent)
        hot = ExplorationAgent()._build_hot_context(bg._sd)

        assert _round_in(hot, r"\[COMBAT Round (\d+)") == _round_in(warm, r"Round (\d+)")
        for p in cs.participants:
            # TWO sources, not one: hot derives `fallen` from HP, warm's [FALLEN] from the
            # is_fallen flag. Every fall site sets both, so they agree — except
            # draethar_inner_fire.py:90, which drives HP to 0 and never sets is_fallen.
            hot_fallen = f"{p.name}(fallen)" in hot
            assert hot_fallen == ("[FALLEN]" in _warm_line_for(warm, p.name))
        assert kael.name + "(fallen)" in hot  # the comparison is not vacuously false==false


class TestCombatEnded:
    async def test_block_is_gone_after_combat_ends(self):
        """AC4: unchanged trunk behaviour, pinned — COMBAT_ENDED is a full-rebuild trigger
        and compose drops a None section."""
        cs = sample_combat_state(round_number=1)
        bg, agent = _make_bg(cs)
        with _mock_db():
            await bg._rebuild_warm_layer()
            cs.round_number = 2
            await bg._process_events(_ui_update(), timed_out=False)
            assert "ACTIVE COMBAT" in _last_warm(agent)

            bg._sd.combat_state = None
            await bg._process_events(
                [GameEvent(event_type=E.COMBAT_ENDED, payload={"outcome": "victory"})], timed_out=False
            )

        assert "ACTIVE COMBAT" not in _last_warm(agent)


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
        _mock_db(),
    ):
        yield


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
    """AC5: the BackgroundProcess belongs to the SESSION, not to the agent that built it."""

    async def test_the_running_loop_updates_the_combat_agent_mid_fight(self):
        """Driven through the live loop, not `_process_events`: a stopped process can still be
        driven by hand, so only the loop can red when the handoff kills it."""
        sd = SessionData(player_id="p1", location_id="accord_guild_hall", room=MagicMock())
        session = MagicMock()
        session.userdata = sd

        with _mock_startup_db():
            exploration = await _enter_exploration(session, sd)
            bg = sd.background
            assert bg is not None
            await _settle(lambda: bg._warm_base is not None, "built its initial warm layer")

            await _exit_exploration(exploration, session)

            combat = CombatAgent()
            session.current_agent = combat
            sd.combat_state = sample_combat_state(round_number=2, hp_current=8)
            try:
                sd.event_bus.publish(GameEvent(event_type=E.COMBAT_UI_UPDATE, payload={}))
                await _settle(lambda: "ACTIVE COMBAT" in combat.instructions, "reached the combat agent")

                assert _is_running(bg)
                warm = str(combat.instructions)
                assert "Round 2" in warm
                assert "- Grosh (enemy) — bloodied" in warm
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
            await _settle(lambda: first._warm_base is not None, "built its initial warm layer")

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
