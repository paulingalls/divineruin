"""Wellspring Echo through registered patron and spell tools."""

from dataclasses import asdict
from unittest.mock import AsyncMock, patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from combat.test_spell_damage_lands import load_combat
from combat.test_synergy_crit_edges import fight, saved_hp
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, published_payloads
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant, spatial_record

import character_spells
import db_mutations
import db_mutations_veil_ward
import db_queries
import event_types as E
import patron_gift_tools
from ability_persistence import update_player_resources
from activate_tools import activate
from combat_turn import declare_phase, resolve_phase
from query_tools import query_info
from session_hydration import hydrate_patron_ability_session
from veil_ward import WardScope
from zhael_fate import FATE

ECHO = "veythar_wellspring_echo"
BURST = "arcane_elemental_burst"
HASTE = "arcane_haste"
ARMED = {"spent": False, "armed": True}
SPENT = {"spent": True}
OTHER_GIFT = {"veythar_lorekeepers_insight": {"spent": False, "pending": None}}


async def caster(world, *spells, total=0, patron="veythar", favor=75, gifts=OTHER_GIFT):
    await configure(
        world,
        patron,
        "mage",
        divine_favor={"patron": patron, "level": favor, "max": 100},
        focus={"current": 2, "max": 10},
        resonance={"current": total},
        patron_gifts=gifts,
    )
    world.ctx.userdata.resonance.current = total
    for spell in spells:
        await character_spells.record_learned(world.ids[0], spell, "training", is_prepared=True, conn=world.pool)


def tools(world):
    return game_tools(world.ctx.userdata, activate, declare_phase, resolve_phase, query_info)


async def declare(world, call, state, spell=BURST, target="foe"):
    host = world.ids[0]
    declaration = {
        **defend(host),
        "kind": "ability",
        "action": spell,
        "targets": [target],
        "argument_type": "cold" if spell == BURST else "",
    }
    return await call(
        "declare_phase",
        declarations=[declaration, *[defend(p.id) for p in state.participants if p.id != host]],
    )


def receipt(cast, *, focus, ordinary):
    assert cast["wellspring_echo"] == {
        "id": ECHO,
        "name": "Wellspring Echo",
        "focus_saved": focus,
        "ordinary_resonance": ordinary,
        "resonance_generated": ordinary * 2,
    }
    assert cast["resonance_generated"] == ordinary * 2
    assert all(word in cast["dm_cue"] for word in ("Wellspring Echo", f"{focus} Focus", f"{ordinary * 2} Resonance"))


async def landed(world, state, result):
    cast = result["packets"][0]["cast"]
    receipt(cast, focus=3, ordinary=2)
    assert await saved_hp(state) == 94
    saved = await row(world, 0)
    assert saved["focus"]["current"] == 2
    assert saved["resonance"]["current"] == world.ctx.userdata.resonance.current == 4
    assert saved["patron_gifts"] == {**OTHER_GIFT, ECHO: SPENT}


async def resolve_burst(call):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(3)),
        patch("dice.roll", return_value=_damage_die(6)),
    ):
        return await call("resolve_phase")


async def wellspring_combat_scenario(world):
    await caster(world, BURST)
    session = world.ctx.userdata
    call = tools(world)
    async with fight(world) as state:
        participant(state, world.ids[0]).archetype_id = "mage"
        spatial_record(state)["positions"]["foe"] = {"x": 30, "y": 0, "z": 0}
        await declare(world, call, state)
        with pytest.raises(ToolError, match="costs 3, you have 2"):
            await call("resolve_phase")
        ability = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == ECHO)
        before = await row(world, 0)
        await call("activate", id=ability["id"])
        assert f'activate(id="{ECHO}")' in ability["activation_hint"]
        armed = await row(world, 0)
        assert armed["patron_gifts"][ECHO] == ARMED
        assert (armed["focus"], armed["resonance"]) == (before["focus"], before["resonance"])
        await declare(world, call, session.combat_state)
        events_before = len(published_payloads(session.room))
        await landed(world, state, await resolve_burst(call))
        assert [
            gift["state"]
            for event in published_payloads(session.room)[events_before:]
            if event["type"] == E.PATRON_ABILITIES_UPDATED
            for gift in event["abilities"]
            if gift["id"] == ECHO
        ] == ["spent"]
        await call("resolve_phase")
        await declare(world, call, session.combat_state)
        with pytest.raises(ToolError, match="costs 3, you have 2"):
            await call("resolve_phase")

        await update_player_resources(world.ids[0], focus=3, conn=world.pool)
        await declare(world, call, session.combat_state)
        events_before = len(published_payloads(session.room))
        ordinary = (await resolve_burst(call))["packets"][0]["cast"]
        assert "wellspring_echo" not in ordinary and ordinary["resonance_generated"] == 2
        assert (await row(world, 0))["focus"]["current"] == 0
        assert all(
            event["type"] != E.PATRON_ABILITIES_UPDATED for event in published_payloads(session.room)[events_before:]
        )


SCENARIOS = {ECHO: ("veythar_wellspring:arm", wellspring_combat_scenario, [()])}


@pytest.mark.parametrize(
    "spell,target,reason",
    [(HASTE, "foe", "isn't a spell you know"), (BURST, "missing_foe", "requires live participant anchors")],
)
async def test_refused_cast_preserves_echo(world, spell, target, reason):
    await caster(world, BURST)
    call = tools(world)
    async with fight(world) as state:
        spatial_record(state)["positions"]["foe"] = {"x": 30, "y": 0, "z": 0}
        await call("activate", id=ECHO)
        before = await row(world, 0)
        with pytest.raises(ToolError, match=reason):
            await declare(world, call, state, spell=spell, target=target)
            await call("resolve_phase")
        assert await row(world, 0) == before
        await declare(world, call, state)
        await landed(world, state, await resolve_burst(call))


async def test_failed_phase_commit_preserves_echo_and_retries(world, monkeypatch):
    await caster(world, BURST)
    session = world.ctx.userdata
    call = tools(world)
    async with fight(world) as state:
        spatial_record(state)["positions"]["foe"] = {"x": 30, "y": 0, "z": 0}
        await call("activate", id=ECHO)
        await declare(world, call, state)
        declared = session.combat_state.to_dict()
        player = await row(world, 0)
        mirrors = asdict(session.party)
        session.room.local_participant.publish_data.reset_mock()
        save = db_mutations.save_combat_state

        async def fail_after_write(combat_id, data, *, conn=None):
            await save(combat_id, data, conn=conn)
            staged = await load_combat(combat_id, conn=conn)
            caster_row = await db_queries.get_player(world.ids[0], conn=conn)
            assert participant(staged, "foe").hp_current == 94
            assert caster_row is not None and caster_row["patron_gifts"][ECHO] == SPENT
            raise RuntimeError("injected after damage and Echo spend")

        with monkeypatch.context() as fault:
            fault.setattr(db_mutations, "save_combat_state", fail_after_write)
            with pytest.raises(RuntimeError, match="injected after damage and Echo spend"):
                await resolve_burst(call)
        assert (await load_combat(state.combat_id)).to_dict() == session.combat_state.to_dict() == declared
        assert await row(world, 0) == player and asdict(session.party) == mirrors
        session.room.local_participant.publish_data.assert_not_called()
        await landed(world, state, await resolve_burst(call))


async def test_fate_hold_freezes_echo_until_cast_completes(world):
    await caster(world, BURST)
    await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": SPENT})
    session = world.ctx.userdata
    host, guest = world.ids
    lifecycle = _live_party(session, host, guest)
    try:
        call = tools(world)
        async with fight(world, ally=True) as state:
            spatial_record(state)["positions"].update(
                foe={"x": 30, "y": 0, "z": 0}, **{guest: {"x": 0, "y": 10, "z": 0}}
            )
            await call("activate", id=ECHO)
            await declare(world, call, state)
            with patch.object(
                patron_gift_tools, "write_state", AsyncMock(wraps=patron_gift_tools.write_state)
            ) as writes:
                offer = (await resolve_burst(call))["fate_offer"]
                assert (offer["roll_kind"], offer["roller_id"]) == ("save", "foe")
                assert guest in offer["eligible_followers"]
                assert await saved_hp(state) == 100
                held = await row(world, 0)
                assert (held["focus"]["current"], held["resonance"]["current"], held["patron_gifts"][ECHO]) == (
                    2,
                    4,
                    ARMED,
                )
                session.combat_state = await load_combat(state.combat_id)
                continuation = session.combat_state.ally_continuation
                assert continuation is not None
                frozen = continuation["steps"]["cast_packet"]
                receipt(frozen, focus=3, ordinary=2)
                with (
                    session._bind_authenticated_actor(guest, 1, lifecycle.require_authorized),
                    patch("dice.roll", return_value=_damage_die(6)),
                ):
                    result = await call("activate", id=FATE, offer_id=offer["offer_id"], keep="original")
                await landed(world, state, result)
                assert [c.args for c in writes.await_args_list if c.kwargs["gift_id"] == ECHO] == [(host, SPENT)]
    finally:
        await lifecycle.aclose()


@pytest.mark.parametrize("warded", [False, True])
async def test_exploration_echo_doubles_modified_generation(world, warded):
    await caster(world, HASTE, "arcane_prestidigitation", total=4)
    session = world.ctx.userdata
    call = tools(world)
    session.location_id = world.ids[0]
    scope = WardScope.location(session.location_id)
    if warded:
        await db_mutations_veil_ward.write_ward(scope, "cleric", None, dismissible=True, conn=world.pool)
    try:
        await call("activate", id=ECHO)
        if not warded:
            cantrip = await call("activate", id="arcane_prestidigitation")
            assert cantrip["resonance_generated"] == 0 and "wellspring_echo" not in cantrip
            saved = await row(world, 0)
            assert (saved["patron_gifts"][ECHO], saved["resonance"]["current"]) == (ARMED, 4)
        events_before = len(published_payloads(session.room))
        cast = await call("activate", id=HASTE)
        receipt(cast, focus=5, ordinary=1 if warded else 3)
        assert cast["ward_active"] is warded
        after = await row(world, 0)
        assert after["focus"]["current"] == 2
        assert after["resonance"]["current"] == session.resonance.current == (4 if warded else 8)
        assert after["concentration"] == {"spell_id": HASTE}
        assert after["patron_gifts"][ECHO] == SPENT
        assert [
            gift["state"]
            for event in published_payloads(session.room)[events_before:]
            if event["type"] == E.PATRON_ABILITIES_UPDATED
            for gift in event["abilities"]
            if gift["id"] == ECHO
        ] == ["spent"]
    finally:
        if warded:
            await db_mutations_veil_ward.dismiss_ward(scope, conn=world.pool)


async def test_direct_spell_activation_during_combat_settles_echo(world):
    await caster(world, HASTE)
    call = tools(world)
    async with fight(world):
        await call("activate", id=ECHO)
        receipt(await call("activate", id=HASTE, target_id=world.ids[0]), focus=5, ordinary=3)
        assert (await row(world, 0))["patron_gifts"][ECHO] == SPENT


async def test_reconnect_preserves_echo_and_new_session_clears_it(world):
    await caster(world)
    session = world.ctx.userdata
    host = world.ids[0]
    call = tools(world)
    await hydrate_patron_ability_session(session, host, conn=world.pool)
    await call("activate", id=ECHO)
    await hydrate_patron_ability_session(session, host, conn=world.pool)
    ability = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == ECHO)
    assert "armed" in ability["activation_hint"]
    assert (await row(world, 0))["patron_gifts"][ECHO] == ARMED

    fresh = make_context(player_id=host, room=session.room).userdata
    await hydrate_patron_ability_session(fresh, host, conn=world.pool)
    assert (await row(world, 0))["patron_gifts"] == {**OTHER_GIFT, ECHO: {"spent": False}}
    await game_tools(fresh, activate)("activate", id=ECHO)
    assert (await row(world, 0))["patron_gifts"][ECHO] == ARMED


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"favor": 74}, "Requires Exalted tier"),
        ({"patron": "mortaen"}, "requires a follower of veythar"),
        ({"gifts": {ECHO: SPENT}}, "Already spent"),
    ],
)
async def test_ineligible_echo_activation_refuses(world, options, reason):
    await caster(world, **options)
    before = await row(world, 0)
    with pytest.raises(ToolError, match=reason):
        await tools(world)("activate", id=ECHO)
    assert await row(world, 0) == before
