"""Player session initialization stays private across exploration handback."""

import json
from typing import cast
from unittest.mock import MagicMock

import pytest
from patron_ability_walk import AbilityWalk

import event_types as E
from exploration_agent import ExplorationAgent
from game_events import publish_game_event


async def test_exploration_handback_targets_the_payload_player(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        await w.use("veythar_lorekeepers_library")
        room = cast(MagicMock, w.sd.room)
        room.local_participant.publish_data.reset_mock()
        await ExplorationAgent()._publish_session_init(w.sd)
        send = room.local_participant.publish_data.await_args
        assert send is not None
        event = json.loads(send.args[0])
        assert event["character"]["player_id"] == w.player
        assert event["abilities"][1]["spent"]
        assert send.kwargs.get("destination_identities") == [w.player]


async def test_player_session_init_rejects_broadcast_before_delivery():
    room = MagicMock()
    bus = MagicMock()
    with pytest.raises(ValueError, match="target its player"):
        await publish_game_event(room, E.SESSION_INIT, {"character": {"player_id": "private"}}, bus)
    room.local_participant.publish_data.assert_not_called()
    bus.publish.assert_not_called()
