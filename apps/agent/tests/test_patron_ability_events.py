"""Committed patron snapshots through the real data-channel publisher."""

import json
from typing import cast
from unittest.mock import MagicMock, patch

from patron_ability_walk import AbilityWalk

import db_session_queries


async def test_initial_snapshot_and_activation_are_committed_and_recipient_scoped(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        payload = await db_session_queries.get_session_init_payload(w.player)
        assert payload.get("abilities") == await w.abilities()
        assert payload["character"]["player_id"] == w.player
        rows = payload["abilities"]
        assert [r["state"] for r in rows] == ["locked", "ready", "locked"]
        captured = []

        async def sent(data, **kwargs):
            event = json.loads(data)
            if event["type"] == "patron_abilities_updated":
                row = await w.row()
                assert row["patron_gifts"]["veythar_lorekeepers_library"]["spent"] is True
                captured.append((event, kwargs))

        cast(MagicMock, w.sd.room).local_participant.publish_data.side_effect = sent
        await w.use("veythar_lorekeepers_library")
        assert len(captured) == 1
        event, kwargs = captured[0]
        assert kwargs["destination_identities"] == [w.player]
        assert event["abilities"] == await w.abilities()
        assert event["abilities"][1]["state"] == "spent"


async def test_unbound_session_has_empty_abilities(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "none", "level": 0, "max": 100})
        payload = await db_session_queries.get_session_init_payload(w.player)
        assert payload.get("abilities") == []


async def test_rest_entry_and_decay_snapshots_follow_committed_state(dev_db_pool):
    from datetime import UTC, datetime, timedelta

    import patron_ability_events
    import session_hydration
    from session_data import SessionData

    async with AbilityWalk(dev_db_pool) as w:
        events = []

        async def sent(data, **kwargs):
            event = json.loads(data)
            if event["type"] == "patron_abilities_updated":
                assert kwargs["destination_identities"] == [event["player_id"]]
                assert (
                    event["abilities"]
                    == patron_ability_events.snapshot(w.player, await w.row(), await w.revision())["abilities"]
                )
                events.append(event)

        cast(MagicMock, w.sd.room).local_participant.publish_data.side_effect = sent
        await w.use("veythar_lorekeepers_library")
        await w.command("rest", {"rest_type": "short"})
        await w.command("rest", {"rest_type": "long"})
        assert [e["abilities"][1]["state"] for e in events] == ["spent", "spent", "ready"]
        await w.use("veythar_lorekeepers_library")
        now = datetime.now(UTC)
        await w.patch(
            divine_favor={
                "patron": "veythar",
                "level": 40,
                "max": 100,
                "last_whisper_level": 0,
                "last_served_at": (now - timedelta(days=8)).isoformat(),
            }
        )
        await session_hydration.apply_session_favor_decay(w.sd, w.player, await w.row(), conn=dev_db_pool, now=now)
        assert events[-1]["abilities"][1]["state"] == "locked"
        assert events[-1]["abilities"][1]["spent"] is True
        await w.patch(
            divine_favor={"patron": "zhael", "level": 60, "max": 100},
            patron_gifts={"zhael_fates_thread": {"spent": True}},
        )
        # Use the authored per-session id, rather than a second recharge rule.
        from _gods_content import load_gods

        zhael = next(p for p in load_gods() if p["god_id"] == "zhael")
        gift = zhael["layer_3_tier_abilities"]["devoted"]["id"]
        await w.patch(patron_gifts={gift: {"spent": True}})
        fresh = SessionData(player_id=w.player, location_id="millhaven_inn", room=w.sd.room)
        await session_hydration.hydrate_patron_ability_session(fresh, w.player, conn=dev_db_pool)
        assert events[-1]["abilities"][1]["state"] == "ready"
        await w.patch(patron_gifts={gift: {"spent": True}})
        count = len(events)
        await session_hydration.hydrate_patron_ability_session(fresh, w.player, conn=dev_db_pool)
        assert len(events) == count
        assert (await w.row())["patron_gifts"][gift]["spent"] is True


async def test_spend_and_recharge_rollback_publish_nothing(dev_db_pool):
    import pytest

    import patron_gift_tools
    import session_hydration
    from event_bus import EventBus

    async with AbilityWalk(dev_db_pool) as w:
        sends = cast(MagicMock, w.sd.room).local_participant.publish_data
        w.sd.event_bus = EventBus()
        bus = w.sd.event_bus
        write = patron_gift_tools.write_state
        reached = []

        async def fail(*args, **kwargs):
            await write(*args, **kwargs)
            reached.append(True)
            raise ValueError("after spend")

        with patch.object(patron_gift_tools, "write_state", fail):
            await w.use("veythar_lorekeepers_library", error=True)
        assert reached == [True]
        assert not (await w.row()).get("patron_gifts", {}).get("veythar_lorekeepers_library")
        sends.assert_not_awaited()
        assert bus.drain() == []
        await w.patch(
            divine_favor={"patron": "zhael", "level": 40, "max": 61},
            patron_gifts={"zhael_prophecy_fragment": {"spent": True}},
        )
        before = await w.state()
        recharge = patron_gift_tools.recharge

        async def fail_recharge(*args, **kwargs):
            await recharge(*args, **kwargs)
            reached.append(True)
            raise ValueError("after recharge")

        with (
            patch.object(patron_gift_tools, "recharge", fail_recharge),
            pytest.raises(ValueError, match="after recharge"),
        ):
            await session_hydration.hydrate_patron_ability_session(w.sd, w.player, conn=dev_db_pool)
        assert reached == [True, True]
        assert await w.state() == before
        assert w.player not in w.sd.patron_ability_entries
        sends.assert_not_awaited()
        assert bus.drain() == []


async def test_party_quest_favor_publishes_each_committed_recipient(dev_db_pool):
    from unittest.mock import AsyncMock, MagicMock

    from sample_fixtures import make_context

    import patron_ability_events
    from quest_tools import _update_quest_impl

    async with (
        AbilityWalk(dev_db_pool) as primary,
        AbilityWalk(dev_db_pool) as secondary,
        AbilityWalk(dev_db_pool) as unbound,
    ):
        for w in (primary, secondary):
            await w.patch(divine_favor={"patron": "veythar", "level": 24, "max": 61, "last_whisper_level": 0})
        await unbound.patch(divine_favor={"patron": "none", "level": 0, "max": 61})
        content = MagicMock()
        content.get_quest = AsyncMock(
            return_value={
                "id": "native_patron_quest",
                "name": "Favor",
                "stages": [{"id": 0, "on_complete": {"favor": 2}}, {"id": 1, "on_complete": {}}],
            }
        )
        # Quest authoring is owned; the transaction, award and delivery use production implementations.
        events = []

        async def sent(data, **kwargs):
            event = json.loads(data)
            if event["type"] != "patron_abilities_updated":
                return
            assert kwargs["destination_identities"] == [event["player_id"]]
            w = primary if event["player_id"] == primary.player else secondary
            assert event == {
                "type": "patron_abilities_updated",
                **patron_ability_events.snapshot(w.player, await w.row(), await w.revision()),
            }
            assert event["abilities"][1]["state"] == "ready"
            events.append(event)

        cast(MagicMock, primary.sd.room).local_participant.publish_data.side_effect = sent
        context = make_context(
            player_id=primary.player, room=primary.sd.room, party_member_ids=[secondary.player, unbound.player]
        )
        try:
            with context.userdata._bind_authenticated_actor(primary.player, 1, lambda *_: None):
                await _update_quest_impl(context, "native_patron_quest", 0, content=content)
                await _update_quest_impl(context, "native_patron_quest", 1, content=content)
            assert {e["player_id"] for e in events} == {primary.player, secondary.player}
        finally:
            await dev_db_pool.execute("DELETE FROM player_quests WHERE quest_id=$1", "native_patron_quest")
