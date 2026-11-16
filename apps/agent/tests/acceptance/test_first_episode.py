"""The first share starts at the product session entrypoint."""

import json
import re
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from acceptance.first_episode_harness import episode, until
from livekit.agents import llm

import db_queries
import event_types as E
from exploration_agent import ExplorationAgent


@pytest.fixture
def mock_combat_agent_factory():
    yield


@pytest.fixture
def stub_creation_companion_grant():
    yield


@pytest.fixture
def stub_companion_hydrate_io():
    yield


@pytest.mark.asyncio
async def test_volunteered_creation(livekit_server, reset_db_pool, tmp_path):
    async with episode(livekit_server, tmp_path) as run:
        for category, value in (
            ("race", "elari"),
            ("class", "rogue"),
            ("deity", "kaelen"),
            ("name", "Vale"),
            ("backstory", "A wanderer."),
        ):
            receipt = await run.turn("set_creation_choice", category=category, value=value)
            assert not receipt.is_error, receipt.output
            progress = json.loads(receipt.output)["progress"]
            assert progress["phase"] == ("calling" if category == "race" else "identity")
        receipt = await run.turn("finalize_character")
        assert not receipt.is_error, receipt.output
        await until(
            lambda: (
                run.session.current_agent.__class__.__name__ == "OnboardingAgent"
                and run.session.userdata.onboarding_beat == 1
                and run.packets(E.SESSION_INIT)
            )
        )
        saved = await db_queries.get_player(run.player_id)
        assert saved is not None
        assert (saved["race"], saved["class"], saved["deity"]) == ("elari", "rogue", "kaelen")
        assert saved["divine_favor"]["patron"] == "kaelen"
        assert saved["backstory"] == "A wanderer."
        assert run.packets(E.SESSION_INIT)[0]["character"]["name"] == "Vale"
        assert run.session.userdata.onboarding_beat == 1
        assert len(run.model.calls) == 6
        assert len(run.model.receipts) == 6
        assert json.loads(receipt.output)["character"]["name"] == "Vale"


ALLOWED = {
    "race": {"human", "elari", "vaelti"},
    "class": {"warrior", "mage", "rogue", "cleric"},
    "deity": {"veythar", "kaelen", "aelora", "syrath"},
}


@pytest.mark.asyncio
async def test_creation_entry_and_prompt(livekit_server, reset_db_pool, tmp_path):
    import re

    from livekit.agents import llm
    from livekit.agents.llm.utils import build_legacy_openai_schema

    async with episode(livekit_server, tmp_path) as run:
        first = run.packets(E.CREATION_CARDS)[0]["cards"]
        assert {card["id"] for card in first} == ALLOWED["class"]
        opening = run.requests[0]
        text = " ".join(item.text_content or "" for item in opening["chat_ctx"].items if hasattr(item, "text_content"))
        assert "what do you reach for when danger comes" in text.lower()
        assert "already visible" in text and "do NOT call push_creation_cards" in text
        prompt = run.session.current_agent.instructions
        assert isinstance(prompt, str)
        assert "calling and a name" in prompt
        assert "query_info" not in prompt
        assert not re.search(r"Awakening|Devotion|all five|Draethar|paladin", prompt)
        tools = run.session.current_agent.tools
        names = set()
        schemas = {}
        for tool in tools:
            assert isinstance(tool, llm.FunctionTool)
            names.add(tool.info.name)
            schemas[tool.info.name] = build_legacy_openai_schema(tool)["function"]
        assert names == {"push_creation_cards", "set_creation_choice", "finalize_character"}
        assert set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", prompt)) <= names
        assert set(schemas["push_creation_cards"]["parameters"]["properties"]["category"]["enum"]) == set(ALLOWED)
        assert "class and name" in schemas["finalize_character"]["description"]


@pytest.mark.asyncio
async def test_creation_cards_and_rejected_choices(livekit_server, reset_db_pool, tmp_path):
    from dataclasses import asdict

    async with episode(livekit_server, tmp_path) as run:
        for category, expected in ALLOWED.items():
            receipt = await run.turn("push_creation_cards", category=category)
            assert not receipt.is_error, receipt.output
            data = json.loads(receipt.output)
            cards = run.packets(E.CREATION_CARDS)[-1]["cards"]
            assert data["count"] == len(data["options"]) == len(cards) == len(expected)
            assert {option["id"] for option in data["options"]} == expected
            assert {card["id"] for card in cards} == expected
            assert all(card["category"] == category and card["description"] and card["image_url"] for card in cards)
            assert all(option["description"] for option in data["options"])
        for category, value in (
            ("race", "draethar"),
            ("class", "paladin"),
            ("deity", "mortaen"),
            ("deity", "none"),
            ("race", "unknown"),
        ):
            assert run.session.userdata.creation_state is not None
            before = asdict(run.session.userdata.creation_state)
            events = len(run.events)
            receipt = await run.turn("set_creation_choice", category=category, value=value)
            assert receipt.is_error, receipt.output
            assert set(receipt.output.split("Valid: ")[1].split(", ")) == ALLOWED[category]
            assert asdict(run.session.userdata.creation_state) == before
            assert not [
                event
                for event, _ in run.events[events:]
                if event["type"] in (E.CREATION_CARD_SELECTED, E.CREATION_CARDS)
            ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calling,patron,companion,source",
    [
        ("warrior", "kaelen", "companion_lira", None),
        ("mage", "veythar", "companion_kael", "arcane"),
        ("rogue", "syrath", "companion_lira", None),
        ("cleric", "aelora", "companion_tam", "divine"),
    ],
)
async def test_calling_and_name_finalize(livekit_server, reset_db_pool, tmp_path, calling, patron, companion, source):
    import db
    import spells

    async with episode(livekit_server, tmp_path, reload_companions=True) as run:
        from companion_profiles import _companion_profiles

        assert set(_companion_profiles) == {"companion_kael", "companion_lira", "companion_tam", "companion_sable"}
        receipt = await run.turn("finalize_character")
        assert receipt.is_error and "class, name" in receipt.output
        assert await db_queries.get_player(run.player_id) is None
        choices = [("class", calling), ("name", "Vale")]
        if calling == "rogue":
            choices.reverse()
        for index, (category, value) in enumerate(choices):
            receipt = await run.turn("set_creation_choice", category=category, value=value)
            assert not receipt.is_error, receipt.output
            progress = json.loads(receipt.output)
            if index == 0:
                assert progress["guidance"] == f"Remaining: {choices[1][0]}."
                assert progress["progress"]["phase"] == ("identity" if category == "class" else "calling")
                receipt = await run.turn("finalize_character")
                assert receipt.is_error and choices[1][0] in receipt.output
                assert await db_queries.get_player(run.player_id) is None
            else:
                assert progress["guidance"] == "All choices made. Call finalize_character."
                assert progress["progress"]["race"] is None
                assert progress["progress"]["deity"] is None
        receipt = await run.turn("finalize_character")
        assert not receipt.is_error, receipt.output
        await until(
            lambda: (
                run.session.current_agent.__class__.__name__ == "OnboardingAgent"
                and run.session.userdata.onboarding_beat == 1
                and run.packets(E.SESSION_INIT)
            )
        )
        assert run.session.current_agent.__class__.__name__ == "OnboardingAgent"
        assert run.session.userdata.onboarding_beat == 1
        player = await db_queries.get_player(run.player_id)
        assert player is not None
        assert (player["name"], player["race"], player["class"], player["deity"]) == ("Vale", "human", calling, patron)
        assert player["divine_favor"]["patron"] == patron
        assert player["backstory"] == ""
        payload = run.packets(E.SESSION_INIT)[0]
        assert payload["character"] == player
        assert payload["companion"]["id"] == companion
        pool = await db.get_pool()
        rows = await pool.fetch("SELECT companion_id FROM companion_relationships WHERE player_id=$1", run.player_id)
        assert [row["companion_id"] for row in rows] == [companion]
        learned = await pool.fetch("SELECT * FROM character_spells WHERE player_id=$1", run.player_id)
        expected = (
            []
            if source is None
            else sorted(
                min(s.id for s in spells.get_spells_by_source(source) if s.spell_tier == tier)
                for tier in ("cantrip", "minor")
            )
        )
        assert sorted(row["spell_id"] for row in learned) == expected
        assert all(row["is_prepared"] and row["acquisition_track"] == "training" for row in learned)
        exposed = payload["spells"]["core"] + payload["spells"]["learned"]
        assert set(expected) <= {row["spell_id"] for row in exposed}
        assert all(row["is_prepared"] for row in exposed if row["spell_id"] in expected)
        assert len(run.model.calls) == len(run.model.receipts) == 5

        for beat in (1, 2, 3):
            sounds = len(run.packets(E.PLAY_SOUND))
            if beat == 3 and calling == "warrior":
                with patch(
                    "companion_relationship_queries.select_companion_for_archetype",
                    side_effect=ValueError("selection failed"),
                ):
                    failed = await run.turn("advance_onboarding_beat")
                assert failed.is_error
                assert run.session.current_agent.__class__.__name__ == "OnboardingAgent"
                assert run.session.userdata.onboarding_beat == 3
                saved = await db_queries.get_player(run.player_id)
                assert saved is not None
                assert saved["flags"]["onboarding_beat"] == 3
                assert not saved["flags"].get("companion_met")
                assert run.session.userdata.companion is None
                assert len(run.packets(E.PLAY_SOUND)) == sounds
            receipt = await run.turn("advance_onboarding_beat")
            assert not receipt.is_error, receipt.output
            result = json.loads(receipt.output)
            saved = await db_queries.get_player(run.player_id)
            assert saved is not None
            added = run.packets(E.PLAY_SOUND)[sounds:]
            assert [packet["sound_name"] for packet in added] == ["action_advance_onboarding_beat"]
            if beat < 3:
                assert result == {"beat": beat + 1, "beat_name": "market" if beat == 1 else "companion_meeting"}
                assert saved["flags"]["onboarding_beat"] == run.session.userdata.onboarding_beat == beat + 1
            else:
                assert result == {"onboarding_complete": True, "location": "accord_market_square"}
                await until(lambda: run.session.current_agent.__class__.__name__ == "ExplorationAgent")
                assert run.session.userdata.onboarding_beat is None
                assert saved["flags"]["onboarding_beat"] == "complete"
                assert saved["flags"]["companion_met"] is True
                bound = run.session.userdata.companion
                assert bound is not None
                assert bound.id == companion
                active = run.session.current_agent
                assert isinstance(active, ExplorationAgent)
                assert active._agent_type == "city" and active._initial_location == "accord_market_square"
                instructions = active.instructions
                assert isinstance(instructions, str)
                assert bound.name in instructions
                summary = " ".join(
                    item.text_content or "" for item in active.chat_ctx.items if isinstance(item, llm.ChatMessage)
                )
                assert bound.name in summary and "accord_market_square" in summary
                assert "Greyvale quest hook" not in summary
                assert run.session.userdata.location_id == "accord_market_square"
                rows = await pool.fetch(
                    "SELECT companion_id FROM companion_relationships WHERE player_id=$1", run.player_id
                )
                assert [row["companion_id"] for row in rows] == [companion]

        if calling == "warrior":
            from acceptance.rider_walk import finish_first_episode

            await finish_first_episode(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("beat", [3, 4, 5])
async def test_persisted_onboarding_startup(livekit_server, reset_db_pool, tmp_path, beat):
    import db_mutations
    import db_mutations_companion
    from creation_rules import build_character_data

    async def prepare(player_id):
        data = build_character_data("Vale", "human", "warrior", "kaelen", "", created_at=datetime.now(UTC))
        data["session_count"] = 7
        data["location_id"] = "accord_market_square"
        await db_mutations.create_player(player_id, None, data)
        await db_mutations.set_player_flag(player_id, "onboarding_beat", beat)
        if beat > 3:
            await db_mutations.set_player_flag(player_id, "companion_met", True)
            await db_mutations_companion.upsert_companion_relationship(
                player_id,
                "companion_lira",
                relationship_tier=1,
                session_count=4,
                affinity=12,
                session_memories=["Shared the rain."],
            )

    expected = "OnboardingAgent" if beat == 3 else "ExplorationAgent"
    async with episode(livekit_server, tmp_path, prepare=prepare, initial_agent=expected) as run:
        saved = await db_queries.get_player(run.player_id)
        assert saved is not None
        assert saved["session_count"] == 8
        state = run.session.userdata
        assert state.location_id == "accord_market_square"
        if beat > 3:
            active = run.session.current_agent
            assert isinstance(active, ExplorationAgent)
            assert active._agent_type == "city" and active._initial_location == "accord_market_square"
        relationship = await db_queries.get_companion_relationship(run.player_id, "companion_lira")
        if beat == 3:
            assert saved["flags"]["onboarding_beat"] == state.onboarding_beat == 3
            assert state.companion is None and relationship is None
            prompt = run.session.current_agent.instructions
            assert isinstance(prompt, str)
            assert "Lira" in prompt
        else:
            assert state.onboarding_beat is None
            assert saved["flags"]["onboarding_beat"] == "complete"
            assert run.packets(E.SESSION_INIT)[0]["character"]["flags"]["onboarding_beat"] == "complete"
            assert relationship is not None
            assert state.companion is not None
            assert state.companion.id == "companion_lira"
            assert state.companion.session_count == relationship["session_count"] == 5
            assert state.companion.affinity == relationship["affinity"] == 12
            assert state.companion.session_memories == relationship["session_memories"] == ["Shared the rain."]


@pytest.mark.parametrize("companion_id", ["companion_kael", "companion_lira", "companion_tam", "companion_sable", None])
def test_three_beat_onboarding_surface(companion_id):
    from companion_profiles import get_companion_profile
    from onboarding_agent import OnboardingAgent
    from onboarding_tools import advance_onboarding_beat

    for beat in (1, 2, 3):
        active = OnboardingAgent(onboarding_beat=beat, companion_id=companion_id)
        prompt = active.instructions
        assert isinstance(prompt, str)
        assert re.findall(r"### Beat (\d+)", prompt) == ["1", "2", "3"]
        assert prompt.count("**Complete when:**") == 3
        assert not re.search(
            r"\b(?:guild[- ]hall|tavern|Hearthstone|Greyvale|move_player|when the player moves)\b", prompt, re.I
        )
        names = set()
        for tool in active.tools:
            assert isinstance(tool, llm.FunctionTool)
            names.add(tool.info.name)
        assert "move_player" not in names
        if companion_id:
            profile = get_companion_profile(companion_id)
            assert profile.onboarding_meeting in prompt and profile.name in prompt
            if profile.non_verbal:
                assert f"[{profile.voice_id}," not in prompt and "does not speak" in prompt
            else:
                assert f"[{profile.voice_id}," in prompt
        else:
            assert "Do NOT name them" in prompt
            assert not any(name in prompt for name in ("Kael", "Lira", "Tam", "Sable"))
    description = advance_onboarding_beat.info.description
    assert description is not None
    assert re.findall(r"Beat (\d+)", description) == ["1", "2", "3"]
