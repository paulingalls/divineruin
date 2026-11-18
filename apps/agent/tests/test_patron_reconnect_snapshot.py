"""A party reconnect refreshes committed favor without recharging session uses."""

import json
from typing import cast
from unittest.mock import MagicMock, patch

from patron_ability_walk import AbilityWalk
from session_lifecycle.test_party_connection import _make_mods, _participant, _recording_room

import db
import db_queries
from participant_lifecycle import _setup_party_join
from progression_tools import _award_divine_favor_core
from session_data import SessionData


async def test_reconnect_refreshes_favor_crossing_during_absence_without_recharge(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "veythar", "level": 24, "max": 61, "last_whisper_level": 0},
            patron_gifts={"veythar_lorekeepers_library": {"spent": True}},
        )
        room, handlers = _recording_room()
        room.isconnected.return_value = True
        room.local_participant.publish_data = cast(MagicMock, w.sd.room).local_participant.publish_data
        sd = SessionData(player_id="host", location_id="millhaven_inn", room=room)
        mods = _make_mods(await w.row())
        owner = _setup_party_join(room, sd, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
        try:
            handlers["participant_connected"](_participant(w.player))
            assert await owner.authorize(w.player) is not None
            initial = json.loads(room.local_participant.publish_data.await_args.args[0])
            assert initial["character"]["divine_favor"]["level"] == 24
            assert not initial["abilities"][1]["eligible"]
            handlers["participant_disconnected"](_participant(w.player))
            async with db.transaction() as conn:
                await db_queries.get_player(w.player, conn=conn, for_update=True)
                await _award_divine_favor_core(w.player, 2, "party quest", conn=conn, pending_events=[])
            room.local_participant.publish_data.reset_mock()
            with patch("session_hydration.hydrate_patron_ability_session") as entry:
                handlers["participant_connected"](_participant(w.player))
                assert await owner.authorize(w.player) is not None
                entry.assert_not_called()
            send = room.local_participant.publish_data.await_args
            assert send is not None, "reconnect did not refresh the disconnected follower"
            event = json.loads(send.args[0])
            assert send.kwargs["destination_identities"] == [w.player]
            assert event["character"]["divine_favor"]["level"] == 26
            assert event["abilities"][1]["eligible"] and event["abilities"][1]["spent"]
            assert not event["abilities"][1]["available"]
        finally:
            await owner.aclose()
