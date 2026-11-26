import json
from uuid import uuid4

import pytest
from acceptance.mawling_harness import MawlingHarness

import choir_scene
import db_mutations


@pytest.mark.parametrize(
    ("location", "destroyed"),
    [("ashmark_corrupted_front", False), ("ashmark_lost_voices", True)],
    ids=["fresh-front", "destroyed-home"],
)
async def test_choir_offer_is_absent(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, location: str, destroyed: bool
) -> None:
    monkeypatch.setenv("CONTENT_CACHE_PREFIX", f"choir_home_offer_{uuid4().hex}:")
    h = MawlingHarness()
    try:
        await h.prepare((16, 16), companion=None, location=location)
        if destroyed:
            key = choir_scene.key(location)
            record = {"location_id": location, "source_id": key, "status": "destroyed"}
            await db_mutations.set_player_flag(h.players[0], key, json.dumps(record))
        receipt = await h.command("enter_location", {"location_id": location})
        assert receipt["choir"] is None
    finally:
        await h.close()
