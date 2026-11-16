"""The episode receipt serializes grants and rolls back with its enclosing fight."""

import asyncio
from unittest.mock import patch

import pytest
from acceptance.first_episode_settlement_harness import assert_settled
from acceptance.first_episode_settlement_harness import fragment_player as fragment_player
from sample_fixtures import make_context, make_mock_room, published_payloads

import db_queries
from combat_end import end_combat
from mode_tools import enter_mode


async def test_episode_rolls_back_with_combat_and_can_retry(fragment_player):
    ctx = await fragment_player()
    sd = ctx.userdata
    before = (list(sd.session_quests_progressed), list(sd.recent_events), published_payloads(sd.room))
    with patch("choir_scene.end", side_effect=RuntimeError("abort after episode writes")):
        with pytest.raises(RuntimeError, match="abort after episode writes"):
            await end_combat(ctx, "fled")
    assert await db_queries.get_player_flag_value(sd.player_id, "first_episode") == "rider"
    assert await db_queries.get_player_quest(sd.player_id, "greyvale_anomaly") is None
    assert not any(row["id"] == "greyvale_veil_fragment" for row in await db_queries.get_player_inventory(sd.player_id))
    assert before == (sd.session_quests_progressed, list(sd.recent_events), published_payloads(sd.room))
    assert sd.combat_state is not None
    await end_combat(ctx, "fled")
    await assert_settled(ctx)


async def test_two_sessions_settle_the_saved_episode_once(fragment_player):
    first = await fragment_player()
    second = make_context(
        first.userdata.player_id,
        location_id="accord_guild_infirmary",
        room=make_mock_room(),
        companion_id="companion_lira",
    )
    await enter_mode(second, "combat", "fragment_shadeling", "Concurrent session")
    async with asyncio.timeout(10):
        await asyncio.gather(end_combat(first, "fled"), end_combat(second, "fled"))
    await assert_settled(first if first.userdata.session_quests_progressed else second)
    assert sum(bool(ctx.userdata.session_quests_progressed) for ctx in (first, second)) == 1
