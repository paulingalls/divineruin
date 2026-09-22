"""finalize_character's fire-and-forget portrait task never reaches the network from a unit test.

Unstubbed, the task POSTs to the REST server's /api/images/generate (paid image generation when
a dev server is up) and is cancelled mid-connect when the test loop ends; the orphaned anyio
coroutine then fails a LATER test with "coroutine ... was never awaited".
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from creation_tools import finalize_character
from session_data import CreationState, SessionData


async def test_finalize_opens_no_http_client_for_the_portrait():
    cs = CreationState(
        phase="identity", race="human", class_choice="mage", deity=None, name="Aric", backstory="Seeker."
    )
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="test_portrait_io", location_id="", room=None, creation_state=cs)
    payload = {"character": {"name": "Aric"}, "location": None, "quests": [], "inventory": []}
    with (
        patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock),
        patch("creation_tools.db_session_queries.get_session_init_payload", AsyncMock(return_value=payload)),
        patch("httpx.AsyncClient") as client,
    ):
        await finalize_character._func(ctx)  # type: ignore[attr-defined]
        for _ in range(5):
            await asyncio.sleep(0)
    client.assert_not_called()
