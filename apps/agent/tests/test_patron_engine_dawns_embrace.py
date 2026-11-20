import json
from dataclasses import replace
from types import SimpleNamespace

from _dawns_embrace_fixtures import EMBRACE, SPENT, aim, damage_ally, embrace_fight
from _death_ward_fixtures import watch_spend
from _mortaen_threshold_fixtures import FOE, active, attack_event, events, rolls
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import game_tools
from sample_fixtures import make_context
from test_aelora_gift import _live_party
from test_patron_engine_death_ward import WARD, hit, resolve_until, saved_target

import db_mutations
from activate_tools import activate
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from mode_tools import enter_mode
from session_data import CompanionState
from session_hydration import hydrate_patron_ability_session
from tool_support import SOUND_PLAYER_FALLEN


async def caught(world, target_id, receipt, hp, donor_index=1):
    target = active(world).get_participant(target_id)
    assert (target.hp_current, target.is_fallen, target.is_dead, target.death_save_failures) == (
        hp,
        False,
        False,
        0,
    ), receipt
    assert await saved_target(world, target) == target
    if target.type == "player":
        assert (await row(world, world.ids.index(target_id)))["hp"]["current"] == hp
    donor = await row(world, donor_index)
    assert donor["patron_gifts"][EMBRACE] == {"spent": True}
    assert receipt["gift_triggered"] == "Dawn's Embrace"
    assert receipt["gift_owner"] == {"id": world.ids[donor_index], "name": donor["name"]}
    assert receipt["gift_target"] == {"id": target.id, "name": target.name}
    assert target.name in receipt["dm_cue"] and donor["name"] in receipt["dm_cue"]


async def registered_damage_catches_ally(world, inner):
    async with embrace_fight(world, patron="mortaen" if inner else "aelora") as call:
        if inner:
            ward = await damage_ally(world, call)
            assert (
                ward["gift_triggered"] == "Death Ward" and active(world).get_participant(world.ids[0]).hp_current == 1
            )
            assert (await row(world, 0))["patron_gifts"][WARD] == {"spent": True}
            assert EMBRACE not in (await row(world))["patron_gifts"]
        donor_before = await row(world)
        observed = watch_spend(world, index=1)
        receipt = await damage_ally(world, call, inner=inner)
        await caught(world, world.ids[0], receipt, 10)
        assert (await row(world))["hp"] == donor_before["hp"]
        assert active(world).get_participant(world.ids[1]).hp_current == 7
        assert "Dawn's Resilience" not in str(receipt)
        assert not any(e.get("sound_name") == SOUND_PLAYER_FALLEN for e in events(world))
        published = world.ctx.userdata.room.local_participant.publish_data
        assert not any(
            kwargs.get("destination_identities") == [world.ids[1]] and json.loads(args[0])["type"] == "hp_changed"
            for args, kwargs in published.call_args_list
        )
        if not inner:
            assert attack_event(world, active(world).get_participant(FOE).name)["context"] != "killing_blow"
            assert (receipt["context"], receipt["dramatic"]) == ("", False)
        [(event, recipients, committed, revision)] = observed
        assert recipients == [world.ids[1]] and event["player_id"] == world.ids[1]
        assert event["patron_revision"] == revision and committed["patron_gifts"] == SPENT
        assert next(a for a in event["abilities"] if a["id"] == EMBRACE)["state"] == "spent"


async def companion_caught(world, maximum, expected):
    session = world.ctx.userdata
    session.companion = CompanionState(id="companion_kael", name="Kael")
    async with embrace_fight(world) as call:
        companion = active(world).get_participant(session.companion.id)
        companion.hp_max, companion.hp_current = maximum, min(4, maximum)
        receipt = await damage_ally(world, call, target_id=companion.id)
        await caught(world, companion.id, receipt, expected)
        assert session.companion.is_conscious and not session.companion.session_memories
        assert not any(e.get("sound_name") == SOUND_PLAYER_FALLEN for e in events(world))


async def draining_hit(world):
    async with embrace_fight(world) as call:
        attacker = active(world).get_participant(FOE)
        attacker.hp_current, attacker.hp_max = 10, 30
        receipt = await hit(world, call, damage=10, self_heal="damage_dealt")

        assert receipt["damage"] == 10
        await caught(world, world.ids[0], receipt, 10)
        assert receipt["self_healed"] == 4
        attacker = active(world).get_participant(FOE)
        assert attacker.hp_current == (await saved_target(world, attacker)).hp_current == 14


async def fallen_donor(world):
    async with embrace_fight(world) as call:
        donor_id = world.ids[1]
        receipt = await damage_ally(world, call, target_id=donor_id)
        assert receipt["target_fallen"] and "gift_triggered" not in receipt
        assert not (await row(world))["patron_gifts"]
        await caught(world, world.ids[0], await damage_ally(world, call, inner=True), 10)
        donor = active(world).get_participant(donor_id)
        assert donor.is_fallen and donor.hp_current == 0


async def recharges(world):
    companion_id = "companion_kael"
    world.ctx.userdata.companion = CompanionState(id=companion_id, name="Kael")
    async with embrace_fight(world) as call:
        companion = active(world).get_participant(companion_id)
        companion.hp_current = 4
        for participant in active(world).participants:
            participant.reaction_ids = []
        await aim(world, call, companion_id, world.ids[0])
        with rolls(*[15] * 12):
            packets = await resolve_until(
                call, lambda r: r["packets"] if any(p["actor_id"] == "mawling_2" for p in r["packets"]) else None
            )
        first, second = [p for p in packets if p["actor_id"] in (FOE, "mawling_2") and "damage" in p]
        assert first["gift_triggered"] == "Dawn's Embrace"
        assert second["target_fallen"] and "gift_triggered" not in second
        assert (await row(world))["patron_gifts"] == SPENT
        await call("end_combat", outcome="fled")

    ctx = make_context(player_id=world.ids[0], party_member_ids=world.ids[1:], room=world.ctx.userdata.room)
    fresh = SimpleNamespace(ctx=ctx, ids=world.ids, pool=world.pool)
    session = ctx.userdata
    lifecycle = _live_party(session, *world.ids)
    try:
        await db_mutations.update_player_hp(world.ids[0], 4, conn=world.pool)
        await hydrate_patron_ability_session(session, world.ids[1], conn=world.pool)
        assert (await row(world))["patron_gifts"] == {EMBRACE: {"spent": False}}
        call = game_tools(session, enter_mode, end_combat, declare_phase, resolve_phase, activate)
        await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
        await caught(fresh, world.ids[0], await damage_ally(fresh, call), 10)
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)
        await lifecycle.aclose()


async def lower_id_spends(world):
    async with embrace_fight(world) as call:
        session = world.ctx.userdata
        higher = world.ids[1]
        # A strict prefix sorts first. Keep the pre-existing donor second in id order.
        lower = higher[:-1]
        await world.pool.execute(
            "INSERT INTO players (player_id, data) SELECT $1, data FROM players WHERE player_id = $2",
            lower,
            higher,
        )
        world.ids.append(lower)
        session.party.members.append(replace(session.member_state(higher), player_id=lower))
        lifecycle = _live_party(session, *world.ids)
        try:
            assert session.present_member_ids[1:] == (higher, lower) and lower < higher
            await caught(world, world.ids[0], await damage_ally(world, call), 10, donor_index=2)
            assert not (await row(world))["patron_gifts"]
        finally:
            await lifecycle.aclose()


async def scenario(world, run, *args):
    await run(world, *args)


SCENARIOS = {
    EMBRACE: (
        "patron_zero_hp:trigger_dawns_embrace",
        scenario,
        [
            (registered_damage_catches_ally, False),
            (registered_damage_catches_ally, True),
            (companion_caught, 20, 10),
            (companion_caught, 23, 11),
            (companion_caught, 1, 1),
            (fallen_donor,),
            (recharges,),
            (lower_id_spends,),
            (draining_hit,),
        ],
    )
}
