import json
from datetime import datetime
from unittest.mock import patch

import pytest
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolContext, ToolError
from sample_fixtures import make_context

import db_activity_queries
import event_types as E
from _gods_content import load_gods
from patron_action_tools import _record_patron_action_impl, record_patron_action
from patron_favor import get_patron_tier

VEYTHAR = next(god for god in load_gods() if god["god_id"] == "veythar")
ACTIONS = VEYTHAR["favor_actions"]["positive"] + VEYTHAR["favor_actions"]["negative"]
PRIOR = "2026-09-01T00:00:00+00:00"


async def seed_favor(pool, level=10, patron="veythar"):
    player_id = "patron_action_player"
    await seed_player(pool, player_id=player_id)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps({"patron": patron, "level": level, "max": 100, "last_whisper_level": 3, "last_served_at": PRIOR}),
    )
    return player_id


async def invoke(player_id, action_id):
    context = make_context(player_id=player_id)
    published = []

    async def capture(room, event_type, payload, event_bus=None):
        committed = await db_activity_queries.get_divine_favor(player_id)
        assert committed is not None
        published.append((event_type, payload, committed["level"]))

    with patch("patron_action_tools.publish_game_event", capture):
        response = await _record_patron_action_impl(context, action_id)
    return json.loads(response), published


@pytest.mark.parametrize("row", ACTIONS, ids=lambda row: row["action"])
async def test_each_authored_action_persists_and_publishes_real_delta(dev_db_pool, row):
    assert len(ACTIONS) == 8
    player_id = await seed_favor(dev_db_pool)
    response, published = await invoke(player_id, row["action"])
    expected = max(0, min(10 + row["amount"], 100))
    stored = await db_activity_queries.get_divine_favor(player_id)
    assert stored is not None
    assert stored["level"] == expected
    assert response == {
        "action_id": row["action"],
        "amount_applied": expected - 10,
        "level": expected,
        "max": 100,
        "previous_tier": get_patron_tier({"patron": "veythar", "level": 10, "max": 100}),
        "tier": get_patron_tier(stored),
    }
    assert len(published) == 1
    event_type, payload, committed_level = published[0]
    assert event_type == E.DIVINE_FAVOR_CHANGED and committed_level == expected
    assert payload == {
        "new_level": expected,
        "previous_level": 10,
        "patron_id": "veythar",
        "last_whisper_level": 3,
        "amount": expected - 10,
        "reason": f"Patron action '{row['action']}'",
        "max": 100,
        "player_id": player_id,
    }
    if row["amount"] > 0:
        assert datetime.fromisoformat(stored["last_served_at"]) > datetime.fromisoformat(PRIOR)
    else:
        assert stored["last_served_at"] == PRIOR


@pytest.mark.parametrize(
    "level,action_id,expected",
    [
        (99, "solved_puzzle", 100),
        (2, "destroyed_knowledge", 0),
        (38, "solved_puzzle", 43),
        (41, "destroyed_knowledge", 36),
    ],
)
async def test_clamps_and_reports_tier_crossings(dev_db_pool, level, action_id, expected):
    player_id = await seed_favor(dev_db_pool, level)
    response, published = await invoke(player_id, action_id)
    assert response["amount_applied"] == expected - level
    assert response["previous_tier"] == get_patron_tier({"patron": "veythar", "level": level, "max": 100})
    assert response["tier"] == get_patron_tier({"patron": "veythar", "level": expected, "max": 100})
    assert published[0][1]["amount"] == expected - level
    assert published[0][2] == expected
    if level in (38, 41):
        assert response["previous_tier"] != response["tier"]


@pytest.mark.parametrize(
    "patron,level,action_id,error",
    [
        ("none", 10, "solved_puzzle", "Unbound"),
        ("veythar", 10, "", "action_id"),
        ("veythar", 10, "defended_innocent", "not authored"),
        ("veythar", -1, "solved_puzzle", "level"),
        ("veythar", 101, "destroyed_knowledge", "level"),
    ],
)
async def test_refusal_does_not_write_or_publish(dev_db_pool, patron, level, action_id, error):
    player_id = await seed_favor(dev_db_pool, level, patron)
    before = await db_activity_queries.get_divine_favor(player_id)
    context = make_context(player_id=player_id)
    published = []

    async def capture(*args, **kwargs):
        published.append((args, kwargs))

    with patch("patron_action_tools.publish_game_event", capture):
        with pytest.raises(ToolError, match=error):
            await _record_patron_action_impl(context, action_id)
    assert await db_activity_queries.get_divine_favor(player_id) == before
    assert published == []


def test_openai_strict_schema_requires_one_string_id():
    parsed = ToolContext([record_patron_action]).parse_function_tools("openai", strict=True)
    assert len(parsed) == 1
    schema = parsed[0]["function"]["parameters"]
    assert schema["required"] == ["action_id"]
    assert schema["properties"] == {"action_id": {"type": "string"}}
