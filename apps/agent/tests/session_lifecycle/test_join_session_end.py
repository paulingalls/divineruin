import asyncio
from unittest.mock import MagicMock

import pytest

from session_data import SessionData


class TestJoinSessionEnd:
    def test_the_hook_is_registered_on_the_rtc_session(self):
        import agent

        assert agent.server._session_end_fnc is agent._join_session_end

    @pytest.mark.asyncio
    async def test_it_does_not_return_until_the_recap_is_published(self):
        from agent import _join_session_end

        published = False

        async def recap():
            nonlocal published
            await asyncio.sleep(0)
            published = True

        sd = SessionData(player_id="p1", location_id="")
        sd.session_end_task = asyncio.create_task(recap())
        ctx = MagicMock()
        ctx.primary_session.userdata = sd

        await _join_session_end(ctx)

        assert published is True

    @pytest.mark.asyncio
    async def test_it_does_not_return_until_the_multiplayer_inputs_are_closed(self):
        from agent import _join_session_end

        closed = False

        async def close_inputs():
            nonlocal closed
            await asyncio.sleep(0)
            closed = True

        sd = SessionData(player_id="p1", location_id="")
        sd.multiplayer_close_task = asyncio.create_task(close_inputs())
        ctx = MagicMock()
        ctx.primary_session.userdata = sd

        await _join_session_end(ctx)

        assert closed is True

    @pytest.mark.asyncio
    async def test_it_returns_quietly_when_there_is_nothing_to_join(self):
        from agent import _join_session_end

        no_session = MagicMock()
        type(no_session).primary_session = property(
            lambda _s: (_ for _ in ()).throw(RuntimeError("No AgentSession was started for this job"))
        )
        await _join_session_end(no_session)

        never_ended = MagicMock()
        never_ended.primary_session.userdata = SessionData(player_id="p1", location_id="")
        await _join_session_end(never_ended)

    @pytest.mark.asyncio
    async def test_it_joins_both_tasks_and_preserves_both_failures(self):
        from agent import _join_session_end

        recap_error = OSError("recap failed")
        multiplayer_error = OSError("multiplayer cleanup failed")

        async def fail(error):
            await asyncio.sleep(0)
            raise error

        sd = SessionData(player_id="p1", location_id="")
        sd.session_end_task = asyncio.create_task(fail(recap_error))
        sd.multiplayer_close_task = asyncio.create_task(fail(multiplayer_error))
        ctx = MagicMock()
        ctx.primary_session.userdata = sd

        with pytest.raises(BaseExceptionGroup) as caught:
            await _join_session_end(ctx)

        assert set(caught.value.exceptions) == {recap_error, multiplayer_error}
