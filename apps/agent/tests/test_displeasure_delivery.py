from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from speech_handles import completed_handle

import event_types as E
from background_process import BackgroundProcess
from bg_speech import PendingSpeech, SpeechPriority
from event_bus import GameEvent
from god_whisper_data import get_god_profile
from progression_tools import _award_divine_favor_core
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
    assert sd.displeasure_heard_by == (set() if should_mark else {"player_1"})
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


async def test_contrary_action_at_favor_floor_still_queues_displeasure():
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(
        return_value={"patron": "kaelen", "level": 0, "max": 100, "last_whisper_level": 0}
    )
    mutations = MagicMock()
    mutations.update_divine_favor = AsyncMock()
    pending = []
    await _award_divine_favor_core(
        "player_1",
        -5,
        "Patron action 'fled_battle'",
        conn=MagicMock(),
        pending_events=pending,
        mutations=mutations,
        activities=activities,
    )
    assert pending[0][1]["amount"] == 0
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", patron_id="kaelen")
    bg = BackgroundProcess(session=MagicMock(), session_data=sd)
    bg._handle_events([GameEvent(event_type=event_type, payload=payload) for event_type, payload in pending])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].is_displeasure


async def test_discarded_displeasure_can_be_queued_again():
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", patron_id="kaelen")
    bg = BackgroundProcess(session=MagicMock(), session_data=sd)
    contrary = GameEvent(
        event_type=E.DIVINE_FAVOR_CHANGED,
        payload={
            "player_id": "player_1",
            "patron_id": "kaelen",
            "new_level": 25,
            "last_whisper_level": 0,
            "amount": -5,
            "reason": "Patron action 'fled_battle'",
        },
    )
    newer = GameEvent(event_type=E.WORLD_EVENT, payload={"event_id": "god_whisper:other", "patron_id": "kaelen"})
    bg._handle_events([contrary, newer])
    with (
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.deliver_speech", new=AsyncMock(return_value=True)),
        patch("background_process.db_activity_queries.get_divine_favor", new=AsyncMock(return_value=None)),
    ):
        await bg._deliver_speech()
    assert sd.displeasure_heard_by == set()
    bg._handle_events([contrary])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].is_displeasure


async def test_failed_displeasure_can_be_queued_again_and_success_spends_latch():
    sd = SessionData(player_id="player_1", location_id="accord_guild_hall", patron_id="kaelen")
    bg = BackgroundProcess(session=MagicMock(), session_data=sd)
    contrary = GameEvent(
        event_type=E.DIVINE_FAVOR_CHANGED,
        payload={
            "player_id": "player_1",
            "patron_id": "kaelen",
            "new_level": 25,
            "last_whisper_level": 0,
            "amount": -5,
            "reason": "Patron action 'fled_battle'",
        },
    )
    bg._handle_events([contrary, contrary])
    assert len(bg._speech_queue) == 1
    with (
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.deliver_speech", new=AsyncMock(side_effect=[False, True])),
    ):
        await bg._deliver_speech()
        assert sd.displeasure_heard_by == set()
        bg._handle_events([contrary])
        await bg._deliver_speech()
    assert sd.displeasure_heard_by == {"player_1"}
    bg._handle_events([contrary])
    assert bg._speech_queue == []


def _contrary(player_id="player_1", patron_id="kaelen"):
    return GameEvent(
        event_type=E.DIVINE_FAVOR_CHANGED,
        payload={
            "player_id": player_id,
            "patron_id": patron_id,
            "amount": -5,
            "new_level": 25,
            "last_whisper_level": 0,
            "reason": "Patron action 'fled_battle'",
        },
    )


def _party_background():
    sd = SessionData(player_id="player_1", location_id="hall", patron_id="kaelen")
    sd.party.members.append(SessionData(player_id="player_2", location_id="hall", patron_id="aelora").party.primary)
    bg = BackgroundProcess(session=MagicMock(), session_data=sd)
    bg._rebuild_warm_layer = AsyncMock(return_value=True)
    return sd, bg


@pytest.fixture
def successful_delivery():
    with (
        patch("game_events.publish_game_event", new_callable=AsyncMock),
        patch("background_process.asyncio.sleep", new_callable=AsyncMock),
        patch("background_process.deliver_speech", new=AsyncMock(return_value=True)) as delivery,
    ):
        yield delivery


async def test_new_primary_hears_displeasure_once_without_changing_previous_heard_state(successful_delivery):
    sd, bg = _party_background()
    bg._handle_events([_contrary()])
    await bg._deliver_speech()
    assert sd.displeasure_heard_by == {"player_1"}
    assert bg._speech_queue == []
    sd.handoff_primary("player_1")
    await bg.primary_changed()
    event = _contrary("player_2", "aelora")
    bg._handle_events([event, event])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].recipient_id == "player_2"
    assert get_god_profile("aelora").displeasure_prompt in bg._speech_queue[0].instructions
    assert sd.displeasure_heard_by == {"player_1"}
    await bg._deliver_speech()
    assert sd.displeasure_heard_by == {"player_1", "player_2"}
    bg._handle_events([event])
    assert bg._speech_queue == []
    assert sd.displeasure_heard_by == {"player_1", "player_2"}


def test_session_displeasure_state_is_fresh_and_old_latch_is_absent():
    sd = SessionData(player_id="player_1", location_id="hall")
    other = SessionData(player_id="player_2", location_id="hall")
    assert sd.displeasure_heard_by == other.displeasure_heard_by == set()
    sd.displeasure_heard_by.add("player_1")
    assert other.displeasure_heard_by == set()
    assert not hasattr(sd, "displeasure_whisper_queued")


async def test_handoff_drops_undelivered_displeasure_without_marking_recipient(successful_delivery):
    sd, bg = _party_background()
    bg._handle_events([_contrary()])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].recipient_id == "player_1"
    assert sd.displeasure_heard_by == set()
    sd.handoff_primary("player_1")
    await bg.primary_changed()
    assert bg._speech_queue == []
    assert sd.displeasure_heard_by == set()
    bg._handle_events([_contrary("player_2", "aelora")])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].recipient_id == "player_2"
    assert sd.displeasure_heard_by == set()
    await bg._deliver_speech()
    assert sd.displeasure_heard_by == {"player_2"}


async def test_displeasure_delivery_marks_queued_recipient_after_primary_changes(successful_delivery):
    sd, bg = _party_background()
    bg._handle_events([_contrary()])

    async def handoff_during_delivery(*args):
        sd.handoff_primary("player_1")
        await bg.primary_changed()
        return True

    successful_delivery.side_effect = handoff_during_delivery
    await bg._deliver_speech()
    assert sd.displeasure_heard_by == {"player_1"}
    bg._handle_events([_contrary("player_2", "aelora")])
    assert len(bg._speech_queue) == 1
    assert bg._speech_queue[0].recipient_id == "player_2"


async def test_recipientless_displeasure_fails_loudly(successful_delivery):
    sd, bg = _party_background()
    bg._speech_queue.append(PendingSpeech(SpeechPriority.CRITICAL, "displeasure", is_displeasure=True))
    with pytest.raises(AssertionError):
        await bg._deliver_speech()
    assert sd.displeasure_heard_by == set()
