from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy
from acceptance.seeds import seed_player_with_pools
from acceptance.test_kaelen_iron_resolve_capstone import required_player
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party

import db_mutations
from activate_tools import activate
from check_tools import check
from combat_death_save import request_death_save
from combat_turn import declare_phase, resolve_phase
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


LUCKY = "zhael_lucky"
FATE = "zhael_fates_thread"
SPENT = {"spent": True}


async def lucky_save_setup(world, gifts=None):
    from conditions import apply_condition

    await seed_player_with_pools(world.pool, player_id=world.ids[0], class_="mage")
    await configure(
        world,
        "zhael",
        "mage",
        location_id="millhaven_inn",
        divine_favor={"patron": "zhael", "level": 0, "max": 100},
        conditions=apply_condition(apply_condition([], "hollowed"), "blessed"),
        patron_gifts=gifts or {},
    )
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    return game_tools(session, check, activate, query_info, rest)


async def open_lucky_save(call):
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(12), _d20(1)]) as dice,
        patch("condition_bonus.dice_roll", return_value=_d20(3)) as bonus,
    ):
        offer = (await call("check", roll={**SAVE, "dc": 30}))["fate_offer"]
        assert dice.call_count == 2 and bonus.call_count == 1
    assert offer["die"] == 1
    return {"id": LUCKY, "offer_id": offer["offer_id"]}, offer


def lucky_projection(packet):
    return next(a for a in packet["abilities"] if a["id"] == LUCKY)


def dice_events(world):
    return [e for e in published_payloads(world.ctx.userdata.room) if e["type"] == "dice_roll"]


async def lucky_save(world, fate_spent, chose_fate=False):
    gifts = {FATE: SPENT, "zhael_prophecy_fragment": SPENT} if fate_spent else {}
    call = await lucky_save_setup(world, gifts)
    before = await row(world, 0)
    patron = await call("query_info", kind="patron")
    expected = {LUCKY} if fate_spent else {FATE, LUCKY}
    assert patron["layer_1_gift"]["spent"] == fate_spent
    args, offer = await open_lucky_save(call)
    assert {a["id"]: a["eligible_followers"] for a in offer["abilities"]} == {
        ability: world.ids[:1] for ability in expected
    }
    assert lucky_projection(patron)["available"] and lucky_projection(patron)["tier"] == "Acknowledged"
    assert not dice_events(world)
    assert (await row(world, 0))["conditions"] == before["conditions"]
    if chose_fate:
        fate_args = {**args, "id": FATE}
        with patch("check_resolution.dice_roll", side_effect=[_d20(20), _d20(10)]):
            await call("activate", **fate_args)
        with pytest.raises(ToolError, match="taken"):
            await call("activate", **args)
        kept = await call("activate", **fate_args, keep="reroll")
        assert kept["roll"] == 10
        assert (await row(world, 0))["patron_gifts"] == {FATE: SPENT}
        assert lucky_projection(await call("query_info", kind="patron"))["available"]
        assert [e["roll"] for e in dice_events(world)] == [10]
        return
    with pytest.raises(ToolError, match="keep"):
        await call("activate", **args, keep="original")
    with patch("check_resolution.dice_roll") as dice, patch("condition_bonus.dice_roll") as bonus:
        result = await call("activate", **args)
        dice.assert_not_called()
        bonus.assert_not_called()
    assert result["roll"] == 20 and result["outcome"] == "success"
    assert result["total"] == offer["total"] + 19 < result["dc"]
    assert result["margin"] == result["total"] - result["dc"]
    assert result["effect_applied"] is None and result["narrative_hint"] == "critical success"
    after = await row(world, 0)
    assert after["hp"] == before["hp"]
    assert [c["type"] for c in after["conditions"]] == ["hollowed"]
    assert after["patron_gifts"] == {**gifts, LUCKY: SPENT}
    with pytest.raises(ToolError, match="current"):
        await call("activate", **args)
    assert [e["roll"] for e in dice_events(world)] == [20]
    assert dice_events(world)[0]["success"] and dice_events(world)[0]["dramatic"]
    snapshots = [e for e in published_payloads(world.ctx.userdata.room) if e["type"] == "patron_abilities_updated"]
    assert len(snapshots) == 1 and lucky_projection(snapshots[0])["state"] == "spent"
    await call("rest", rest_type="short")
    assert lucky_projection(await call("query_info", kind="patron"))["state"] == "spent"
    assert (await row(world, 0))["patron_gifts"][LUCKY] == SPENT
    await call("rest", rest_type="long")
    assert lucky_projection(await call("query_info", kind="patron"))["available"]
    assert not (await row(world, 0))["patron_gifts"].get(LUCKY, {}).get("spent")
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        again = await call("check", roll=SAVE)
    assert LUCKY in {a["id"] for a in again["fate_offer"]["abilities"]}


async def lucky_attack(world, face):
    flip = face == 20
    gifts = {} if flip else {FATE: SPENT}
    await configure(world, "zhael", "mage", patron_gifts=gifts)
    pid = world.ids[0]
    target = _enemy("foe", 30)
    state = _build_state(pid, pid, [target])
    required_player(state, pid).attack_mod = 25
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, declare_phase, resolve_phase, activate)
    try:
        await call("declare_phase", declarations=[attack(pid, "foe"), defend("foe")])
        with (
            patch("check_resolution.dice_roll", side_effect=[_d20(face)]) as dice,
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)) as damage,
        ):
            result = await call("resolve_phase")
            if flip:
                offer = result["fate_offer"]
                assert {a["id"] for a in offer["abilities"]} == {LUCKY, FATE}
                saved = await db_mutations.load_combat_state(state.combat_id)
                assert required_player(saved, "foe").hp_current == 30
                assert not dice_events(world)
                result = await call("activate", id=LUCKY, offer_id=offer["offer_id"])
            assert "fate_offer" not in result and dice.call_count == 1
            assert damage.call_count == (0 if flip else 1)

        packet = result["packets"][0]
        assert (packet["hit"], packet["critical"], packet["damage"]) == (not flip, False, 0 if flip else 4)
        saved = await db_mutations.load_combat_state(state.combat_id)
        foe = required_player(saved, "foe")
        assert (foe.hp_current, foe.conditions) == (30 if flip else 26, target.conditions)
        [event] = dice_events(world)
        assert event["roll"] == (1 if flip else face)
        assert event["total"] >= target.ac + 2 and event["success"] == (not flip)
        assert not event["critical"] and (not flip or event["dramatic"])
        assert (await row(world, 0))["patron_gifts"] == ({LUCKY: SPENT} if flip else gifts)
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def lucky_death_save(world):
    await configure(world, "zhael", "mage", hp={"current": 0, "max": 20}, patron_gifts={FATE: SPENT})
    pid = world.ids[0]
    state = _build_state(pid, pid, [_enemy("foe", 30)])
    faller = required_player(state, pid)
    faller.hp_current, faller.is_fallen, faller.death_save_failures = 0, True, 2
    session = world.ctx.userdata
    session.combat_state = state
    call = game_tools(session, request_death_save, activate)
    try:
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        with patch("combat_resolution.dice_roll", side_effect=[_d20(1)]) as dice:
            offer = (await call("request_death_save"))["fate_offer"]
            assert offer["abilities"] == [{"id": LUCKY, "eligible_followers": [pid]}]
            assert faller.death_save_failures == 2 and not dice_events(world)
            result = await call("activate", id=LUCKY, offer_id=offer["offer_id"])
            assert dice.call_count == 1
        assert result["revived"] and result["roll"] == 20
        player = await row(world, 0)
        assert player["hp"]["current"] == 1 and player["patron_gifts"] == {FATE: SPENT, LUCKY: SPENT}
        saved = await db_mutations.load_combat_state(state.combat_id)
        revived = required_player(saved, pid)
        assert (revived.hp_current, revived.is_fallen, revived.death_save_failures, revived.death_save_successes) == (
            1,
            False,
            0,
            0,
        )
        assert [(e["roll_type"], e["roll"]) for e in dice_events(world)] == [("death_save", 20)]
    finally:
        await db_mutations.delete_combat_state(state.combat_id)


async def lucky_skill(world):
    await configure(
        world,
        "zhael",
        "mage",
        location_id=world.ctx.userdata.location_id,
        flags={"concealed": False},
        patron_gifts={FATE: SPENT},
    )
    pid = world.ids[0]
    call = game_tools(world.ctx.userdata, check, activate)
    counter = "SELECT use_counter FROM skill_advancement WHERE player_id=$1 AND skill_id='stealth'"
    roll = {
        "kind": "skill",
        "skill": "stealth",
        "difficulty": "moderate",
        "context_description": "Hide from the guard",
        "hearing_only": False,
    }
    with patch("check_resolution.dice_roll", side_effect=[_d20(1)]) as dice:
        offer = (await call("check", roll=roll))["fate_offer"]
        assert offer["abilities"] == [{"id": LUCKY, "eligible_followers": [pid]}]
        assert await world.pool.fetchval(counter, pid) is None
        assert not (await row(world, 0))["flags"]["concealed"] and not dice_events(world)
        result = await call("activate", id=LUCKY, offer_id=offer["offer_id"])
        assert dice.call_count == 1
    assert result["roll"] == 20 and (await row(world, 0))["flags"]["concealed"]
    assert await world.pool.fetchval(counter, pid) == 1
    assert [e["roll"] for e in dice_events(world)] == [20]


async def lucky_scenario(world, exercise, *args):
    await exercise(world, *args)


SCENARIOS = {
    LUCKY: (
        "zhael_fate:activate",
        lucky_scenario,
        [
            (lucky_save, False),
            (lucky_save, True),
            (lucky_save, False, True),
            (lucky_attack, 20),
            (lucky_attack, 14),
            (lucky_death_save,),
            (lucky_skill,),
        ],
    )
}


@pytest.mark.parametrize(
    ("patron", "index", "face", "spent"),
    [
        ("zhael", 0, 17, False),
        ("zhael", 0, 1, True),
        ("none", 1, 1, False),
        ("aelora", 1, 1, False),
    ],
)
async def test_lucky_exclusions_leave_fate_open(world, patron, index, face, spent):
    host, guest = world.ids
    await configure(
        world,
        "zhael",
        "mage",
        patron_gifts={LUCKY: SPENT} if spent else {},
        attributes={"wisdom": 16},
    )
    if index == 1:
        await configure(world, patron, "mage", index=1)
    session = world.ctx.userdata
    lifecycle = _live_party(session, host, guest)
    call = game_tools(session, check, activate)
    try:
        with (
            patch("check_resolution.dice_roll", return_value=_d20(face)),
            session._bind_authenticated_actor(world.ids[index], 1, lifecycle.require_authorized),
        ):
            offer = (await call("check", roll=SAVE))["fate_offer"]
        if face == 17:
            assert offer["total"] == 20
        assert offer["abilities"] == [{"id": FATE, "eligible_followers": [host]}]
        with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
            with pytest.raises(ToolError, match="ineligible"):
                await call("activate", id=LUCKY, offer_id=offer["offer_id"])
            assert not dice_events(world)
            assert (await row(world, 0)).get("patron_gifts", {}) == ({LUCKY: SPENT} if spent else {})
            result = await call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
        assert result["roll"] == face and [e["roll"] for e in dice_events(world)] == [face]
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("changed", ["patron", "spend", None])
async def test_lucky_revalidates_persisted_readiness_for_the_authenticated_roller(world, changed):
    host, guest = world.ids
    await configure(world, "zhael", "mage")
    await configure(world, "zhael", "mage", index=1)
    session = world.ctx.userdata
    lifecycle = _live_party(session, host, guest)
    call = game_tools(session, check, activate)
    gifts = {LUCKY: SPENT} if changed == "spend" else {}
    try:
        with (
            patch("check_resolution.dice_roll", return_value=_d20(1)),
            session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized),
        ):
            offer = (await call("check", roll=SAVE))["fate_offer"]
        assert offer["abilities"] == [
            {"id": FATE, "eligible_followers": world.ids},
            {"id": LUCKY, "eligible_followers": [guest]},
        ]
        args = {"id": LUCKY, "offer_id": offer["offer_id"]}
        with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
            with pytest.raises(ToolError, match="ineligible"):
                await call("activate", **args)
        if changed is None:
            with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
                result = await call("activate", **args)
            assert result["roll"] == 20 and [e["roll"] for e in dice_events(world)] == [20]
            assert (await row(world, 0)).get("patron_gifts", {}) == {}
            assert (await row(world, 1))["patron_gifts"] == {LUCKY: SPENT}
            return
        await configure(world, "zhael" if changed == "spend" else "aelora", "mage", index=1, patron_gifts=gifts)
        with session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized):
            with pytest.raises(ToolError, match="spent" if changed == "spend" else "follower of zhael"):
                await call("activate", **args)
        assert not dice_events(world)
        assert (await row(world, 0)).get("patron_gifts", {}) == {}
        assert (await row(world, 1))["patron_gifts"] == gifts
        with session._bind_authenticated_actor(host, 1, lifecycle.require_authorized):
            result = await call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
        assert result["roll"] == 1 and [e["roll"] for e in dice_events(world)] == [1]
    finally:
        await lifecycle.aclose()
