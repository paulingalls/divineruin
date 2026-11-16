"""The first share starts at the product session entrypoint."""

import json

import pytest
from acceptance.first_episode_harness import episode, until

import db_queries
import event_types as E


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
                and getattr(run.session.current_agent, "_background", None) is not None
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

    async with episode(livekit_server, tmp_path) as run:
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
            lambda: getattr(run.session.current_agent, "_background", None) is not None and run.packets(E.SESSION_INIT)
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
