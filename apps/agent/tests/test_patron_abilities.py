"""Follower abilities through the registered DM verbs."""

import pytest
from patron_ability_walk import AbilityWalk

from _gods_content import load_gods

LIBRARY = "veythar_lorekeepers_library"
TRUTH = "valdris_weight_of_truth"


async def test_library_spends_durably_and_requires_long_rest(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as w:
        ability = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert ability["eligible"] and ability["available"] and not ability["spent"]
        result = await w.use(ability["id"])
        authored = load_gods()[0]["layer_3_tier_abilities"]["devoted"]
        assert result["effect"] == authored["effect"]
        assert "narrate" in result["dm_cue"].lower()
        assert 'query_info(kind="creature", target_id=' in result["dm_cue"]
        assert "number" in result["dm_cue"]
        assert (await w.row())["patron_gifts"] == {"other": {"x": 1}, LIBRARY: {"spent": True}}
        before = await w.state()
        await w.connect()
        assert "long rest" in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        await w.command("rest", {"rest_type": "short", "use_song_of_rest": False})
        assert next(a for a in await w.abilities() if a["id"] == LIBRARY)["spent"]
        await w.command("rest", {"rest_type": "long", "use_song_of_rest": False})
        assert next(a for a in await w.abilities() if a["id"] == LIBRARY)["available"]
        await w.use(LIBRARY)


@pytest.mark.parametrize("rest_type", ["short", "long"])
async def test_weight_of_truth_spends_and_recharges(dev_db_pool, rest_type):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "valdris", "level": 0, "max": 100})
        result = await w.use(TRUTH)
        gift = next(g["layer_1_gift"] for g in load_gods() if g["god_id"] == "valdris")
        assert result["effect"] == gift["effect"] and result["dm_cue"]
        assert "short rest" in await w.use(TRUTH, error=True)
        await w.command("rest", {"rest_type": rest_type, "use_song_of_rest": False})
        assert (await w.row())["patron_gifts"][TRUTH] == {"spent": False}
        await w.use(TRUTH)


async def test_promotion_is_visible_without_capability_write(dev_db_pool):
    import db
    import db_queries
    from progression_tools import _award_divine_favor_core

    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "veythar", "level": 39, "max": 100})
        before = await w.state()
        assert "Devoted" in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        assert not next(a for a in await w.abilities() if a["id"] == LIBRARY)["eligible"]
        async with db.transaction() as conn:
            await db_queries.get_player(w.player, conn=conn, for_update=True)
            await _award_divine_favor_core(w.player, 1, "served", conn=conn, pending_events=[])
        row = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert row["eligible"] and row["available"] and not row["spent"]
        assert (await w.row())["patron_gifts"] == before["patron_gifts"]


@pytest.mark.parametrize(
    "favor,cause",
    [
        (None, "no patron"),
        ({"level": 40, "max": 100}, "Unbound"),
        ({"patron": None, "level": 40, "max": 100}, "Unbound"),
        ({"patron": "none", "level": 40, "max": 100}, "Unbound"),
        ({"patron": "syrath", "level": 100, "max": 100}, "veythar"),
    ],
)
async def test_only_the_current_follower_can_spend(dev_db_pool, favor, cause):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor=favor)
        before = await w.state()
        assert cause in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        if favor is not None and favor.get("patron") in (None, "none"):
            assert await w.abilities() == []


async def test_pending_and_always_on_refuse_without_writes(dev_db_pool, monkeypatch):
    import copy
    from functools import partial

    import patron_ability_tools
    import query_patron
    from _gods_content import _validate_gods

    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "veythar", "level": 100, "max": 100})
        before = await w.state()
        rows = copy.deepcopy(load_gods())
        library = rows[0]["layer_3_tier_abilities"]["devoted"]
        library["status"] = "pending"
        _validate_gods(rows)
        monkeypatch.setattr(patron_ability_tools, "load_gods", lambda: rows)
        monkeypatch.setattr(query_patron, "query_patron", partial(query_patron.query_patron, gods_loader=lambda: rows))
        assert "pending" in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        pending = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert not pending["available"] and pending["state"] == "locked" and "pending" in pending["reason"]
        library.update(status="active", recharge="always")
        _validate_gods(rows)
        assert "always-on" in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        ability = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert ability["eligible"] and not ability["available"] and "always-on" in ability["reason"]
        library.update(status="active", recharge="long_rest", resolution="engine", implementation_id="zhael_lucky")
        _validate_gods(rows)
        assert "pending" in await w.use(LIBRARY, error=True)
        assert await w.state() == before
        ability = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert not ability["available"] and ability["state"] == "locked"


@pytest.mark.parametrize(
    "patron,ability_id",
    [
        ("veythar", "veythar_scholars_ward"),
        ("kaelen", "kaelen_warriors_endurance"),
        ("nythera", "nythera_tidewalker"),
    ],
)
async def test_engine_passives_are_eligible_but_never_spend(dev_db_pool, patron, ability_id):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": patron, "level": 0, "max": 100})
        before = await w.state()
        ability = next(a for a in await w.abilities() if a["id"] == ability_id)
        assert ability["status"] == "active" and ability["eligible"] and not ability["available"]
        assert "always-on" in ability["reason"]
        assert "always-on" in await w.use(ability_id, error=True)
        assert await w.state() == before


async def test_per_session_spend_survives_both_rests(dev_db_pool):
    ability = "zhael_prophecy_fragment"
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "zhael", "level": 100, "max": 100})
        await w.use(ability)
        for rest_type in ("short", "long"):
            await w.command("rest", {"rest_type": rest_type, "use_song_of_rest": False})
            assert (await w.row())["patron_gifts"][ability] == {"spent": True}
            assert "new session" in await w.use(ability, error=True)


@pytest.mark.parametrize("spent", [False, True])
async def test_decay_and_promotion_preserve_spent_state(dev_db_pool, spent):
    from datetime import timedelta
    from unittest.mock import patch

    from test_favor_decay_hydration import NOW, _mods

    import db
    import db_queries
    from progression_tools import _award_divine_favor_core
    from session_hydration import hydrate_session_state

    async with AbilityWalk(dev_db_pool) as w:
        markers = {"other": {"x": 1}, **({LIBRARY: {"spent": True}} if spent else {})}
        await w.patch(
            patron_gifts=markers,
            divine_favor={
                "patron": "veythar",
                "level": 42,
                "max": 100,
                "last_whisper_level": 0,
                "last_served_at": (NOW - timedelta(days=8)).isoformat(),
            },
        )
        with patch("game_events.publish_game_event"):
            await hydrate_session_state(w.sd, await w.row(), now=NOW, conn=dev_db_pool, **_mods())
        assert (await w.row())["divine_favor"]["level"] == 37
        rows = await w.abilities()
        assert rows[0]["eligible"]
        library = next(a for a in rows if a["id"] == LIBRARY)
        assert not library["eligible"] and not library["available"] and library["spent"] is spent
        assert "Devoted" in library["reason"]
        async with db.transaction() as conn:
            await db_queries.get_player(w.player, conn=conn, for_update=True)
            await _award_divine_favor_core(w.player, 3, "served", conn=conn, pending_events=[])
        library = next(a for a in await w.abilities() if a["id"] == LIBRARY)
        assert library["eligible"] and library["available"] is (not spent) and library["spent"] is spent
        assert (await w.row())["patron_gifts"] == markers


async def test_guest_does_not_borrow_hosts_patron(dev_db_pool):
    async with AbilityWalk(dev_db_pool) as host, AbilityWalk(dev_db_pool) as guest:
        await guest.patch(divine_favor={"patron": "none", "level": 0, "max": 100})
        host.sd.party.members.append(guest.sd.party.primary)
        before = await guest.state()
        assert "Unbound" in await host.use(LIBRARY, error=True, actor=guest.player)
        assert await guest.state() == before
        assert LIBRARY not in (await host.row())["patron_gifts"]


async def test_primary_entry_restores_once_and_new_session_restores_again(dev_db_pool):
    from test_favor_decay_hydration import _mods

    from session_hydration import hydrate_session_state

    ability = "zhael_prophecy_fragment"
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": "zhael", "level": 100, "max": 100})
        stale = await w.row()
        await w.use(ability)
        await hydrate_session_state(w.sd, stale, conn=dev_db_pool, **_mods())
        assert (await w.row())["patron_gifts"][ability] == {"spent": False}
        await w.use(ability)
        await hydrate_session_state(w.sd, stale, conn=dev_db_pool, **_mods())
        await w.connect(w.sd)
        assert "new session" in await w.use(ability, error=True)
        await w.connect()
        await hydrate_session_state(w.sd, stale, conn=dev_db_pool, **_mods())
        await w.use(ability)
        assert (await w.row())["patron_gifts"][ability] == {"spent": True}


async def test_guest_entry_restores_once_across_reconnect_and_rejoin(dev_db_pool):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    import db_queries
    from participant_lifecycle import _setup_party_join

    ability = "zhael_prophecy_fragment"
    async with AbilityWalk(dev_db_pool) as host, AbilityWalk(dev_db_pool) as guest:
        for w in (host, guest):
            await w.patch(divine_favor={"patron": "zhael", "level": 100, "max": 100})
            await w.use(ability)
        room, handlers = MagicMock(), {}
        room.local_participant.publish_data = AsyncMock()
        room.remote_participants = {}
        room.on.side_effect = lambda event, callback: handlers.setdefault(event, callback)
        res = MagicMock(read_player_resonance=AsyncMock(return_value={"current": 0, "flickering_bonus": 0}))
        conc = MagicMock(read_player_concentration=AsyncMock(return_value={"spell_id": None}))
        lifecycle = _setup_party_join(room, host.sd, queries=db_queries, resonance_mod=res, concentration_mod=conc)
        participant = SimpleNamespace(identity=guest.player)
        try:
            handlers["participant_connected"](participant)
            assert await lifecycle.authorize(guest.player) is not None
            assert (await guest.row())["patron_gifts"][ability] == {"spent": False}
            assert (await host.row())["patron_gifts"][ability] == {"spent": True}
            await host.use(ability, actor=guest.player)
            handlers["participant_disconnected"](participant)
            handlers["participant_connected"](participant)
            assert await lifecycle.authorize(guest.player) is not None
            assert "new session" in await host.use(ability, actor=guest.player, error=True)
            lifecycle.mark_departed(guest.player)
            host.sd.party.members.remove(host.sd.member_state(guest.player))
            handlers["participant_connected"](participant)
            assert await lifecycle.authorize(guest.player) is not None
            assert "new session" in await host.use(ability, actor=guest.player, error=True)
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize(
    "patron, level, gift_id, name, tier, recharge",
    [
        ("mortaen", 0, "mortaen_death_ward", "Death Ward", "Acknowledged", "long_rest"),
        ("orenthel", 75, "orenthel_dawns_embrace", "Dawn's Embrace", "Exalted", "per_session"),
    ],
)
async def test_automatic_gift_discovery_and_direct_activation_refusal(
    dev_db_pool, patron, level, gift_id, name, tier, recharge
):
    async with AbilityWalk(dev_db_pool) as w:
        await w.patch(divine_favor={"patron": patron, "level": level, "max": 100})
        ability = next(a for a in await w.abilities() if a["id"] == gift_id)
        assert (ability["name"], ability["tier"], ability["status"], ability["recharge"]) == (
            name,
            tier,
            "active",
            recharge,
        )
        assert ability["available"] and not ability["spent"]
        assert "automatically when damage" in ability["activation_hint"]
        before = await w.row()
        assert "cannot be activated directly" in (await w.use(gift_id, error=True)).lower()
        assert await w.row() == before
