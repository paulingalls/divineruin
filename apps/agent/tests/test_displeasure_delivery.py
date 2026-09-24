"""Displeasure speech keeps its sound without changing favor whisper cadence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from speech_handles import completed_handle

import event_types as E
from background_process import BackgroundProcess
from event_bus import GameEvent
from session_data import SessionData


@pytest.mark.parametrize("amount,should_mark", [(-5, False), (5, True)])
async def test_whisper_delivery_marks_only_ordinary_favor(amount, should_mark):
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", patron_id="kaelen")
    session = MagicMock()
    bg = BackgroundProcess(session=session, session_data=sd)
    bg._handle_events(
        [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
                payload={
                    "player_id": "player_1",
                    "patron_id": "kaelen",
                    "new_level": 30,
                    "last_whisper_level": 0,
                    "amount": amount,
                    "reason": "Patron action 'fled_battle'",
                },
            )
        ]
    )
    assert len(bg._speech_queue) == 1
    order = []

    async def publish(*args, **kwargs):
        order.append("sound")

    def reply(**kwargs):
        order.append("speech")
        return completed_handle()

    session.generate_reply = reply
    with (
        patch("game_events.publish_game_event", side_effect=publish),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.db_activity_queries.get_divine_favor", new=AsyncMock(return_value={"level": 30})),
        patch("background_process.db_mutations_divine.mark_favor_whisper_level", new=AsyncMock()) as mark,
    ):
        await bg._deliver_speech()
    assert order == ["sound", "speech"]
    if should_mark:
        mark.assert_awaited_once_with("player_1", 30)
    else:
        mark.assert_not_awaited()


async def test_failed_whisper_delivery_never_marks_favor():
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", patron_id="kaelen")
    bg = BackgroundProcess(session=MagicMock(), session_data=sd)
    bg._handle_events(
        [
            GameEvent(
                event_type=E.DIVINE_FAVOR_CHANGED,
                payload={
                    "player_id": "player_1",
                    "patron_id": "kaelen",
                    "new_level": 30,
                    "last_whisper_level": 0,
                    "amount": 5,
                    "reason": "valor",
                },
            )
        ]
    )
    with (
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.deliver_speech", new=AsyncMock(return_value=False)),
        patch("background_process.db_mutations_divine.mark_favor_whisper_level", new_callable=AsyncMock) as mark,
    ):
        await bg._deliver_speech()
    mark.assert_not_awaited()
