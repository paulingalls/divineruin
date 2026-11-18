from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from acceptance.seeds import seed_player_with_pools
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

from activate_tools import activate
from check_tools import check
from query_tools import query_info
from rest_tools import rest


async def test_unanswered_reroll_settles_original_before_query(world):
    await seed_player_with_pools(world.pool, player_id=world.ids[0], class_="mage")
    await configure(world, "zhael", "mage", location_id="millhaven_inn")
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    call = game_tools(session, check, activate, query_info, rest)
    with patch("check_resolution.dice_roll", side_effect=[_d20(2), _d20(20)]):
        offered = await call(
            "check", roll={"kind": "save", "save_type": "wisdom", "dc": 15, "effect_on_fail": "frightened"}
        )
        offer = offered["fate_offer"]
        assert offer["die"] == 2 and offer["eligible_followers"] == world.ids[:1]
        assert "effect_applied" not in offered
        shown = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"])
        assert shown["reroll"]["die"] == 20
    assert not published_payloads(session.room)
    queried = await call("query_info", kind="patron")
    assert queried["settled_fate"]["effect_applied"] == "frightened"
    assert queried["layer_1_gift"]["spent"]
    assert (await row(world, 0))["patron_gifts"]["zhael_fates_thread"] == {"spent": True}
    assert [event["roll"] for event in published_payloads(session.room) if event["type"] == "dice_roll"] == [2]
    with patch("check_resolution.dice_roll", return_value=_d20(10)):
        immediate = await call(
            "check", roll={"kind": "save", "save_type": "wisdom", "dc": 15, "effect_on_fail": "frightened"}
        )
    assert immediate["effect_applied"] == "frightened" and "fate_offer" not in immediate
    await call("rest", rest_type="short")
    assert (await call("query_info", kind="patron"))["layer_1_gift"]["spent"]
    await call("rest", rest_type="long")
    restored = (await call("query_info", kind="patron"))["layer_1_gift"]
    assert restored["available"] and not restored["spent"]
    with patch("check_resolution.dice_roll", return_value=_d20(10)):
        offered_again = await call("check", roll=SAVE)
    assert offered_again["fate_offer"]["eligible_followers"] == world.ids[:1]


SAVE = {"kind": "save", "save_type": "wisdom", "dc": 15, "effect_on_fail": "frightened"}


async def test_ally_save_declines_without_spending_and_uses_current_patron(world):
    await configure(world, "zhael", "mage")
    await configure(world, "aelora", "mage", index=1)
    session = world.ctx.userdata
    host, guest = world.ids
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, check, activate)
    try:
        with patch("check_resolution.dice_roll", return_value=_d20(2)):
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                packet = await call("check", roll=SAVE)
            offer = packet["fate_offer"]
            assert offer["roller_id"] == guest and offer["eligible_followers"] == [host]
            assert "effect_applied" not in packet and not published_payloads(session.room)
            args = dict(id="zhael_fates_thread", offer_id=offer["offer_id"])
            with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                with pytest.raises(ToolError, match="keep"):
                    await call("activate", **args, keep="random")
                declined = await call("activate", **args, keep="original")
                with pytest.raises(ToolError, match="current"):
                    await call("activate", **args, keep="original")
            assert declined["effect_applied"] == "frightened"
            assert "zhael_fates_thread" not in (await row(world, 0)).get("patron_gifts", {})
            for patron in ("none", "syrath"):
                # Deliberately leave the session's patron cache on Zhael.
                await world.pool.execute(
                    "UPDATE players SET data=jsonb_set(data,'{divine_favor,patron}',to_jsonb($2::text)) WHERE player_id=$1",
                    host,
                    patron,
                )
                with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                    immediate = await call("check", roll=SAVE)
                assert "fate_offer" not in immediate and immediate["effect_applied"] == "frightened"
        assert [event["roll"] for event in published_payloads(session.room) if event["type"] == "dice_roll"] == [
            2,
            2,
            2,
        ]
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize(("keep", "kept_die", "applied"), [("original", 4, "frightened"), ("reroll", 14, None)])
async def test_ally_save_repeats_disadvantage_and_keeps_one_bonus(world, keep, kept_die, applied):
    from conditions import apply_condition

    await configure(world, "zhael", "mage")
    await configure(
        world,
        "aelora",
        "mage",
        index=1,
        conditions=apply_condition(apply_condition([], "hollowed"), "blessed"),
    )
    session = world.ctx.userdata
    host, guest = world.ids
    lifecycle = _live_party(session, *world.ids)
    call = game_tools(session, check, activate)
    try:
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(18), _d20(4), _d20(20), _d20(14)]) as dice,
            patch("condition_bonus.dice_roll", return_value=_d20(3)) as bonus,
        ):
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                offer = (await call("check", roll=SAVE))["fate_offer"]
            assert offer["die"] == 4 and offer["total"] == 7
            args = dict(id="zhael_fates_thread", offer_id=offer["offer_id"])
            with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
                shown = await call("activate", **args)
                assert shown["reroll"] == {"die": 14, "total": 17}
                assert {c["type"] for c in (await row(world, 1))["conditions"]} == {"hollowed", "blessed"}
                chosen = await call("activate", **args, keep=keep)
            assert dice.call_count == 4 and bonus.call_count == 1
        assert chosen["roll"] == kept_die and chosen["effect_applied"] == applied
        assert [c["type"] for c in (await row(world, 1))["conditions"]] == ["hollowed"]
        assert [event["roll"] for event in published_payloads(session.room) if event["type"] == "dice_roll"] == [
            kept_die
        ]
    finally:
        await lifecycle.aclose()
