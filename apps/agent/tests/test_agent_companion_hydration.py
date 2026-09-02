"""Assigned-companion hydration at session start and onboarding first meeting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from companion_profiles import get_companion_profile
from exploration_agent import ExplorationAgent
from onboarding_agent import OnboardingAgent
from session_data import CompanionState, SessionData
from system_prompts import build_system_prompt


def _fake_hydrated_companion(_player_id: str, companion_id: str, name: str) -> CompanionState:
    return CompanionState(id=companion_id, name=name, session_count=1)


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
    async def test_session_start_hydrates_archetype_complement_with_legacy_kael_row(self):
        player = {
            "name": "Aric",
            "class": "warrior",
            "location_id": "accord_guild_hall",
            "flags": {"onboarding_beat": "complete", "companion_met": True},
        }

        _session, hydrate, userdata = await _run_dm_session(player)

        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira")
        companion = userdata.companion
        assert companion is not None
        assert companion.id == "companion_lira"
        assert companion.name == "Lira"
        assert companion.session_count == 1
        assert companion.last_speech_time > 0

    @pytest.mark.asyncio
    async def test_mid_onboarding_reconnect_hydrates_before_dispatch(self):
        player = {
            "name": "Aric",
            "class": "warrior",
            "location_id": "accord_market_square",
            "flags": {"onboarding_beat": 3, "companion_met": True},
        }

        session, hydrate, _userdata = await _run_dm_session(player)

        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira")
        assert isinstance(session.start.call_args.kwargs["agent"], OnboardingAgent)

    @pytest.mark.asyncio
    async def test_completed_onboarding_dispatches_city_agent(self):
        player = {
            "name": "Aric",
            "class": "warrior",
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
        player = {"name": "Aric", "class": "warrior"}

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
        hydrate.assert_awaited_once_with("player_1", "companion_lira", "Lira")
        assert ctx.userdata.companion.id == "companion_lira"

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


class TestCompanionPrompt:
    def test_verbal_companion_section_uses_assigned_profile(self):
        profile = get_companion_profile("companion_lira")

        prompt = build_system_prompt(
            "accord_guild_hall",
            CompanionState(id=profile.id, name=profile.name),
        )

        assert "## Companion — Lira" in prompt
        assert f"[{profile.voice_id}, emotion]" in prompt
        assert profile.speech_style in prompt
        assert all(trait in prompt for trait in profile.personality)
        assert all(mannerism in prompt for mannerism in profile.mannerisms)
        assert "## Companion — Kael" not in prompt
        assert prompt == build_system_prompt(
            "accord_guild_hall",
            CompanionState(id=profile.id, name=profile.name),
        )

    def test_non_verbal_companion_is_profiled_without_dialogue_instruction(self):
        profile = get_companion_profile("companion_sable")

        prompt = build_system_prompt(
            "accord_guild_hall",
            CompanionState(id=profile.id, name=profile.name),
        )

        assert "## Companion — Sable" in prompt
        assert profile.voice_id in prompt
        assert profile.speech_style in prompt
        assert all(trait in prompt for trait in profile.personality)
        assert all(mannerism in prompt for mannerism in profile.mannerisms)
        assert f"[{profile.voice_id}," not in prompt
        assert "narrate" in prompt.lower()
