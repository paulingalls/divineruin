"""Assigned-companion hydration at session start and onboarding first meeting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from companion_profiles import get_companion_profile
from exploration_agent import ExplorationAgent
from onboarding_agent import OnboardingAgent
from session_data import CompanionState, SessionData
from system_prompts import build_system_prompt


def _fake_hydrated_companion(_player_id: str, companion_id: str, name: str, *, player_level: int = 1) -> CompanionState:
    return CompanionState(id=companion_id, name=name, player_level=player_level, session_count=1)


async def _run_dm_session(player: dict) -> tuple[MagicMock, AsyncMock, SessionData]:
    from agent import dm_session

    ctx = MagicMock()
    ctx.job = None
    ctx.room = MagicMock()
    session = MagicMock()
    session.start = AsyncMock()
    session.generate_reply = AsyncMock()

    with (
        patch("agent.AgentSession", return_value=session) as session_factory,
        patch("agent.deepgram.STT"),
        patch("agent.anthropic.LLM"),
        patch("agent._make_tts"),
        patch("agent.inference.VAD"),
        patch("agent.inference.TurnDetector"),
        patch("agent.db_queries.get_player", new_callable=AsyncMock, return_value=player),
        patch("agent.db_queries.get_last_session_summary", new_callable=AsyncMock, return_value=None),
        patch(
            "agent.db_content_queries.get_location",
            new_callable=AsyncMock,
            return_value={"region_type": "city"},
        ),
        patch("session_hydration.hydrate_session_state", new_callable=AsyncMock),
        patch("agent._setup_reconnection"),
        patch("agent._setup_party_join"),
        patch(
            "companion_relationship_queries.hydrate_companion_state",
            new_callable=AsyncMock,
            side_effect=_fake_hydrated_companion,
        ) as hydrate,
    ):
        await dm_session(ctx)

    userdata = session_factory.call_args.kwargs["userdata"]
    return session, hydrate, userdata


class TestReturningPlayerCompanion:
    @pytest.mark.asyncio
    async def test_session_start_hydrates_the_archetype_complement_not_kael(self):
        player = {
            "name": "Aric",
            "class": "warrior",
            "level": 19,
            "location_id": "accord_guild_hall",
            "flags": {"onboarding_beat": "complete", "companion_met": True},
        }

        _session, hydrate, userdata = await _run_dm_session(player)

        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira", player_level=19)
        companion = userdata.companion
        assert companion is not None
        assert companion.id == "companion_lira"
        assert companion.name == "Lira"
        assert companion.player_level == 19
        assert companion.session_count == 1
        assert companion.last_speech_time > 0

    @pytest.mark.asyncio
    async def test_mid_onboarding_reconnect_hydrates_before_dispatch(self):
        player = {
            "name": "Aric",
            "class": "warrior",
            "level": 1,
            "location_id": "accord_market_square",
            "flags": {"onboarding_beat": 3, "companion_met": True},
        }

        session, hydrate, _userdata = await _run_dm_session(player)

        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira", player_level=1)
        assert isinstance(session.start.call_args.kwargs["agent"], OnboardingAgent)

    @pytest.mark.asyncio
    async def test_unassignable_archetype_fails_loud_instead_of_defaulting_to_kael(self):
        """AC5: zero/multi-match archetype aborts session start rather than falling back."""
        player = {
            "name": "Aric",
            "class": "necromancer",
            "level": 1,
            "location_id": "accord_guild_hall",
            "flags": {"onboarding_beat": "complete", "companion_met": True},
        }

        with pytest.raises(ValueError, match="necromancer"):
            await _run_dm_session(player)

    @pytest.mark.asyncio
    async def test_completed_onboarding_dispatches_city_agent(self):
        player = {
            "name": "Aric",
            "class": "warrior",
            "level": 1,
            "location_id": "accord_guild_hall",
            "flags": {"onboarding_beat": "complete", "companion_met": True},
        }

        session, _hydrate, _userdata = await _run_dm_session(player)

        gameplay_agent = session.start.call_args.kwargs["agent"]
        assert isinstance(gameplay_agent, ExplorationAgent)
        assert gameplay_agent._agent_type == "city"


class TestFirstMeetingCompanion:
    @pytest.mark.asyncio
    async def test_beat_three_reads_persisted_class_and_hydrates_complement(self):
        from onboarding_tools import advance_onboarding_beat

        ctx = MagicMock()
        ctx.userdata = SessionData(
            player_id="player_1",
            location_id="accord_market_square",
            onboarding_beat=3,
            creation_state=None,
        )
        player = {"name": "Aric", "class": "warrior", "level": 12}

        with (
            patch("onboarding_tools.db_queries.get_player", new_callable=AsyncMock, return_value=player) as get_player,
            patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock),
            patch(
                "companion_relationship_queries.hydrate_companion_state",
                new_callable=AsyncMock,
                side_effect=_fake_hydrated_companion,
            ) as hydrate,
        ):
            await advance_onboarding_beat._func(ctx)

        get_player.assert_awaited_once_with("player_1")
        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira", player_level=12)
        assert ctx.userdata.companion.id == "companion_lira"
        assert ctx.userdata.companion.player_level == 12

    @pytest.mark.asyncio
    async def test_gameplay_handoff_summary_names_assigned_companion(self):
        from onboarding_tools import advance_onboarding_beat

        ctx = MagicMock()
        ctx.userdata = SessionData(
            player_id="player_1",
            location_id="accord_guild_hall",
            onboarding_beat=5,
            companion=CompanionState(id="companion_lira", name="Lira"),
        )

        with (
            patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock),
            patch("gameplay_agent.create_gameplay_agent", return_value=MagicMock()) as create_agent,
        ):
            await advance_onboarding_beat._func(ctx)

        chat_ctx = create_agent.call_args.kwargs["chat_ctx"]
        summary = " ".join(str(item.content) for item in chat_ctx.items)
        assert "companion Lira" in summary
        assert "companion Kael" not in summary

    @pytest.mark.asyncio
    async def test_gameplay_handoff_without_a_companion_fails_loud(self):
        """The beat-5 guard: reached only if beat 3 persisted the advance but not the companion."""
        from onboarding_tools import advance_onboarding_beat

        ctx = MagicMock()
        ctx.userdata = SessionData(
            player_id="player_1",
            location_id="accord_guild_hall",
            onboarding_beat=5,
            companion=None,
        )

        with (
            patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock) as set_flag,
            patch("gameplay_agent.create_gameplay_agent") as create_agent,
            pytest.raises(ToolError, match="without a companion"),
        ):
            await advance_onboarding_beat._func(ctx)

        set_flag.assert_not_awaited()
        create_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_beat_three_failure_leaves_the_beat_unadvanced(self):
        """The assignment precedes the beat write, so a failed one stays replayable at beat 3."""
        from onboarding_tools import advance_onboarding_beat

        ctx = MagicMock()
        ctx.userdata = SessionData(
            player_id="player_1",
            location_id="accord_market_square",
            onboarding_beat=3,
            creation_state=None,
        )

        with (
            patch(
                "onboarding_tools.db_queries.get_player",
                new_callable=AsyncMock,
                return_value={"name": "Aric", "class": "necromancer", "level": 1},
            ),
            patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock) as set_flag,
            pytest.raises(ValueError, match="necromancer"),
        ):
            await advance_onboarding_beat._func(ctx)

        assert ctx.userdata.onboarding_beat == 3
        assert ctx.userdata.companion is None
        set_flag.assert_not_awaited()


class TestCompanionPrompt:
    def test_verbal_companion_section_uses_assigned_profile(self):
        profile = get_companion_profile("companion_lira")

        prompt = build_system_prompt(
            "accord_guild_hall",
            CompanionState(id=profile.id, name=profile.name),
        )

        assert "## Companion — Lira" in prompt
        assert f"[{profile.voice_id}, emotion]" in prompt
        # Constraint 6: begin_activity(kind="companion_errand") refuses any id but the assigned
        # one, and the prompt is the only channel that can produce it — the DM sees the name and
        # the voice tag everywhere else, never `companion_lira`.
        assert f"Tool id: {profile.id}" in prompt
        assert "companion_kael" not in prompt
        assert profile.speech_style in prompt
        assert all(trait in prompt for trait in profile.personality)
        assert all(mannerism in prompt for mannerism in profile.mannerisms)
        assert "## Companion — Kael" not in prompt
        # Cost model: the section rides the CACHED static layer, so it must not vary with the
        # per-turn mutable half of CompanionState. Reds the moment affinity/session_count/mood
        # is interpolated into it.
        assert prompt == build_system_prompt(
            "accord_guild_hall",
            CompanionState(
                id=profile.id,
                name=profile.name,
                session_count=9,
                affinity=40,
                emotional_state="alert",
                session_memories=["fought a Hollow rider"],
                last_speech_time=1234.5,
            ),
        )

    def test_non_verbal_companion_is_profiled_without_dialogue_instruction(self):
        profile = get_companion_profile("companion_sable")

        prompt = build_system_prompt(
            "accord_guild_hall",
            CompanionState(id=profile.id, name=profile.name),
        )

        assert "## Companion — Sable" in prompt
        assert profile.voice_id in prompt
        assert f"Tool id: {profile.id}" in prompt
        assert profile.speech_style in prompt
        assert all(trait in prompt for trait in profile.personality)
        assert all(mannerism in prompt for mannerism in profile.mannerisms)
        assert f"[{profile.voice_id}," not in prompt
        assert f"{profile.name} is non-verbal" in prompt
        assert "Never use it as a dialogue tag" in prompt
