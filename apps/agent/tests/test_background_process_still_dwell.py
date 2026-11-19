import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from background_process import BackgroundProcess
from event_bus import GameEvent
from session_data import SessionData


async def test_transient_dwell_error_does_not_end_the_background_loop():
    sd = SessionData(player_id="player-1", location_id="accord_guild_hall")
    process = BackgroundProcess(MagicMock(), sd)
    process._rebuild_warm_layer = AsyncMock(return_value=True)
    process._alignment.maybe_tick = AsyncMock()
    process._deliver_speech = AsyncMock()
    dwell = AsyncMock(side_effect=[asyncpg.InterfaceError("connection lost"), ""])

    with patch("still_dwell.advance", dwell):
        process.start()
        run = process._task
        assert run is not None
        try:
            sd.event_bus.publish(GameEvent("test-pulse", {}))
            async with asyncio.timeout(2):
                while dwell.await_count < 2 and not run.done():
                    await asyncio.sleep(0.01)
            assert not run.done()
            assert dwell.await_count == 2
        finally:
            await process.stop()
