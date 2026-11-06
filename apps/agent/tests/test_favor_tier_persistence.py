import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from acceptance.seeds import seed_player
from sample_fixtures import make_context
from speech_handles import completed_handle

import db_activity_queries
import db_mutations_concentration
import db_mutations_resonance
import db_queries
import event_types as E
from participant_lifecycle import _setup_party_join
from patron_action_tools import record_patron_action
from patron_favor import get_patron_tier
from query_tools import query_info
from session_data import SessionData
from session_hydration import hydrate_session_state


async def _reload(pool, player_id, level, tier):
    async with pool.acquire() as conn:
        raw = await conn.fetchval("SELECT data->'divine_favor' FROM players WHERE player_id=$1", player_id)
        favor = json.loads(raw)
        assert favor["level"] == level
        assert favor["max"] == 50
        assert favor["patron"] == "veythar"
        assert "tier" not in favor
        assert await db_activity_queries.get_divine_favor(player_id, conn=conn) == favor
        player = await db_queries.get_player(player_id, conn=conn)
        assert player is not None
        assert player["divine_favor"] == favor
    response = json.loads(await query_info(make_context(player_id=player_id), kind="patron"))
    assert (response["level"], response["max"], response["patron_id"], response["tier"]) == (level, 50, "veythar", tier)
    assert get_patron_tier(favor) == tier
    return player


async def test_favor_and_selection_round_trip_by_action_and_neglect(dev_db_pool):
    player_id = f"favor_round_trip_{uuid4().hex}"
    try:
        await seed_player(dev_db_pool, player_id=player_id)
        await dev_db_pool.execute(
            "UPDATE players SET data=jsonb_set(data, '{divine_favor}', $2::jsonb) WHERE player_id=$1",
            player_id,
            json.dumps(
                {
                    "patron": "veythar",
                    "level": 15,
                    "max": 50,
                    "last_whisper_level": 0,
                    "last_served_at": "2026-09-01T00:00:00+00:00",
                }
            ),
        )
        player = await _reload(dev_db_pool, player_id, 15, "Acknowledged")
        context = make_context(player_id=player_id, room=None)
        for action, steps in (
            ("solved_puzzle", [(20, "Devoted"), (25, "Devoted"), (30, "Devoted"), (35, "Devoted"), (40, "Exalted")]),
            (
                "destroyed_knowledge",
                [(35, "Devoted"), (30, "Devoted"), (25, "Devoted"), (20, "Devoted"), (15, "Acknowledged")],
            ),
            ("solved_puzzle", [(20, "Devoted"), (25, "Devoted"), (30, "Devoted"), (35, "Devoted"), (40, "Exalted")]),
        ):
            for level, tier in steps:
                await record_patron_action(context, action_id=action)
                player = await _reload(dev_db_pool, player_id, level, tier)
        instant = datetime.fromisoformat(player["divine_favor"]["last_served_at"])
        for level in (35, 30, 25, 20):
            instant += timedelta(days=7)
            fresh = SessionData(
                player_id=player_id, location_id="accord_guild_hall", patron_id=player["divine_favor"]["patron"]
            )
            await hydrate_session_state(fresh, player, now=instant)
            assert fresh.patron_id == "veythar"
            assert fresh.favor_loss == ("veythar", 5)
            events = fresh.event_bus.drain()
            assert len(events) == 1 and events[0].event_type == E.DIVINE_FAVOR_CHANGED
            assert events[0].payload["reason"] == "neglect"
            player = await _reload(dev_db_pool, player_id, level, "Devoted")
        instant += timedelta(days=7)
        party = SessionData(player_id=f"host_{uuid4().hex}", location_id="accord_guild_hall")
        voice = MagicMock()
        voice.generate_reply.return_value = completed_handle()
        room = MagicMock()
        room.remote_participants = {}
        handlers = {}
        room.on.side_effect = lambda name, callback: handlers.setdefault(name, callback)
        with patch("session_hydration.datetime") as clock:
            clock.now.return_value = instant
            lifecycle = _setup_party_join(
                room,
                party,
                agent_session=voice,
                queries=db_queries,
                resonance_mod=db_mutations_resonance,
                concentration_mod=db_mutations_concentration,
            )
            try:
                handlers["participant_connected"](SimpleNamespace(identity=player_id))
                assert await lifecycle.authorize(player_id) is not None
            finally:
                await lifecycle.aclose()
        member = next(member for member in party.party.members if member.player_id == player_id)
        assert member.patron_id == "veythar"
        await _reload(dev_db_pool, player_id, 15, "Acknowledged")
        instructions = voice.generate_reply.call_args.kwargs["instructions"]
        assert player["name"] in instructions
        assert "veythar's displeasure" in instructions
        assert "5 favor" in instructions
    finally:
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", player_id)
