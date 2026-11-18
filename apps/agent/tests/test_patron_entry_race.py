"""Overlapping party generations cannot recover the same session use twice."""

import asyncio
from typing import cast
from unittest.mock import MagicMock, patch

from patron_ability_walk import AbilityWalk
from session_lifecycle.test_party_connection import _make_mods, _participant, _recording_room

import session_hydration
from participant_lifecycle import _setup_party_join
from session_data import SessionData


async def test_reconnect_during_first_entry_preserves_the_authorized_spend(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(
            divine_favor={"patron": "zhael", "level": 100, "max": 100},
            patron_gifts={"zhael_prophecy_fragment": {"spent": True}},
        )
        room, handlers = _recording_room()
        room.isconnected.return_value = True
        room.local_participant.publish_data = cast(MagicMock, w.sd.room).local_participant.publish_data
        sd = SessionData(player_id="host", location_id="millhaven_inn", room=room)
        mods = _make_mods(await w.row())
        paused, release = asyncio.Event(), asyncio.Event()
        recharge = session_hydration._recharge_session_abilities
        calls = 0

        async def delayed(pid, conn):
            nonlocal calls
            calls += 1
            if calls == 1:
                paused.set()
                await release.wait()
            await recharge(pid, conn)

        with patch.object(session_hydration, "_recharge_session_abilities", delayed):
            owner = _setup_party_join(room, sd, queries=mods[0], resonance_mod=mods[1], concentration_mod=mods[2])
            try:
                handlers["participant_connected"](_participant(w.player))
                await asyncio.wait_for(paused.wait(), timeout=5)
                handlers["participant_disconnected"](_participant(w.player))
                handlers["participant_connected"](_participant(w.player))
                authorization = asyncio.create_task(owner.authorize(w.player))
                done, _ = await asyncio.wait({authorization}, timeout=0.1)
                if not done:
                    release.set()
                assert await authorization is not None
                await w.connect(sd)
                w.validator = lambda *args: owner.require_authorized(args[0], 2)
                await w.use("zhael_prophecy_fragment")
                release.set()
                await asyncio.gather(*tuple(owner._spawned_joins))
                assert (await w.row())["patron_gifts"]["zhael_prophecy_fragment"]["spent"]
                assert "new session" in await w.use("zhael_prophecy_fragment", error=True)
                assert calls == 1
            finally:
                release.set()
                await owner.aclose()
