"""The warm layer's ACTIVE COMBAT block tracks the fight it describes.

Every test here drives the event handler DIRECTLY (`_process_events`), never a loop tick
and never the 30s bus fallback: on trunk the fallback already heals the warm layer once
the fight goes quiet, so a test that let the timer fire would certify the timer and not
the fix.
"""

import re
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from prompt_fixtures import SAMPLE_LOCATION

import event_types as E
from background_process import BackgroundProcess
from event_bus import GameEvent
from exploration_agent import ExplorationAgent
from session_data import CombatParticipant, CombatState, SessionData

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


def _combat(round_number: int = 1, **grosh_overrides: object) -> CombatState:
    kael = CombatParticipant(id="p_kael", name="Kael", type="player", initiative=18, hp_current=20, hp_max=20, ac=14)
    grosh = CombatParticipant(id="grosh", name="Grosh", type="enemy", initiative=9, hp_current=20, hp_max=20, ac=12)
    for key, value in grosh_overrides.items():
        setattr(grosh, key, value)
    return CombatState(
        combat_id="c1",
        participants=[kael, grosh],
        initiative_order=["p_kael", "grosh"],
        round_number=round_number,
    )


def _participant(combat_state: CombatState, pid: str) -> CombatParticipant:
    p = combat_state.get_participant(pid)
    assert p is not None
    return p


def _make_bg(combat_state: CombatState | None = None) -> tuple[BackgroundProcess, MagicMock]:
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall")
    sd.combat_state = combat_state
    agent = MagicMock()
    agent.update_instructions = AsyncMock()
    return BackgroundProcess(agent=agent, session=MagicMock(), session_data=sd), agent


def _ui_update() -> list[GameEvent]:
    return [GameEvent(event_type=E.COMBAT_UI_UPDATE, payload={})]


def _last_warm(agent: MagicMock) -> str:
    return agent.update_instructions.await_args[0][0]


class TestCombatUiUpdateRefresh:
    async def test_round_and_hp_advance_in_the_warm_layer(self):
        """AC1: a COMBAT_UI_UPDATE driven through the handler re-renders the block."""
        cs = _combat(round_number=1)
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
        bg, agent = _make_bg(_combat(round_number=2))
        await bg._process_events(_ui_update(), timed_out=False)
        assert agent.update_instructions.await_count == 0

    async def test_refresh_issues_no_db_query(self):
        """AC2: the block re-renders from session.combat_state alone.

        Counts awaits rather than raising from a seam: _rebuild_warm_layer wraps its gather
        in `except Exception: return`, so a raising seam would be swallowed and this guard
        would pass while the prompt stayed stale. The round-2 assertion pairs with the counts
        so "refreshed nothing at all" cannot pass either.
        """
        cs = _combat(round_number=1)
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
        cs = _combat(round_number=1)
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
            hot_fallen = f"{p.name}(fallen)" in hot
            assert hot_fallen == ("[FALLEN]" in _warm_line_for(warm, p.name))
        assert kael.name + "(fallen)" in hot  # the comparison is not vacuously false==false


class TestCombatEnded:
    async def test_block_is_gone_after_combat_ends(self):
        """AC4: unchanged trunk behaviour, pinned — COMBAT_ENDED is a full-rebuild trigger
        and compose drops a None section."""
        cs = _combat(round_number=1)
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
