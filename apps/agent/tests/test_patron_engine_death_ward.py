from unittest.mock import patch

import pytest
from _death_ward_fixtures import concentrating, spent_projection, watch_spend
from _mortaen_threshold_fixtures import (
    FOE,
    active,
    attack_event,
    claw,
    declare,
    events,
    fight,
    follower,
    position,
    rolls,
)
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools

import check_resolution_save
import conditions
import db_mutations
from db_queries import get_player_at_patron_revision
from rest_tools import rest
from tool_support import SOUND_HOLLOW_RISE, SOUND_PLAYER_FALLEN

WARD = "mortaen_death_ward"
SPENT = {WARD: {"spent": True}}


async def resolve_until(call, select):
    for _ in range(12):
        match = select(await call("resolve_phase"))
        if match:
            return match
    raise AssertionError("Expected resolution did not arrive")


def enemy_damage(result):
    return next((p for p in result["packets"] if p["actor_id"] == FOE and "damage" in p), None)


async def hit(world, call, *, damage, face=15, **changes):
    position(world)
    await declare(world, call, claw(world, **changes))
    with rolls(face, face, 7, damage=damage):
        return await resolve_until(call, enemy_damage)


async def saved_target(world, target):
    state = active(world)
    snapshot = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
    assert snapshot is not None
    saved = snapshot.get_participant(target.id)
    assert saved is not None
    return saved


async def standing(world, receipt, index=0):
    target = active(world).get_participant(world.ids[index])
    assert (target.hp_current, target.is_fallen, target.is_dead, target.death_save_failures, target.type) == (
        1,
        False,
        False,
        0,
        "player",
    )
    assert await saved_target(world, target) == target
    player = await row(world, index)
    assert player["hp"]["current"] == 1
    assert player["patron_gifts"][WARD] == {"spent": True}
    assert receipt["gift_triggered"] == "Death Ward"
    assert receipt["gift_owner"] == {"id": target.id, "name": target.name}
    assert receipt["dm_cue"] == "Mortaen decides when you cross."


async def enemy_hit(world, face=15, stage=0, solo=False):
    conds = [conditions.apply_condition([], "hollowed")[0] | {"stage": stage}] if stage else []
    async with fight(world, hp=5, max_hp=25, favor=0, conditions=conds) as call:
        if solo:
            session = world.ctx.userdata
            session.multiplayer_owner.lifecycle.mark_departed(world.ids[1])
            assert session.present_member_ids == (world.ids[0],)
        assert follower(world).hp_max == 25
        assert conditions.hollowed_stage(follower(world).conditions) == stage
        observed = watch_spend(world)
        receipt = await hit(world, call, damage=15 if face == 20 else 30, face=face)
        assert receipt["damage"] == 30
        await standing(world, receipt)
        event = attack_event(world, active(world).get_participant(FOE).name)
        assert event["context"] == receipt["context"] == ("natural_20" if face == 20 else "")
        assert (event["roll"], event["success"], event["critical"], event["damage"], event["total"]) == (
            face,
            True,
            face == 20,
            30,
            receipt["attack_total"],
        )
        assert not {SOUND_HOLLOW_RISE, SOUND_PLAYER_FALLEN} & {e.get("sound_name") for e in events(world)}
        spent_projection(observed, world.ids[0])


async def save_hit(world):
    async with fight(world, hp=5, max_hp=25, favor=0) as call:
        observed = watch_spend(world)
        receipt = await hit(
            world,
            call,
            damage=10,
            resolution="save",
            save="DEX",
            dc=30,
            to_hit=0,
            save_success_damage="half",
            conditions_on_failure=[],
            conditions_on_success=[],
        )
        assert receipt["damage"] == 10
        await standing(world, receipt)
        spent_projection(observed, world.ids[0])


async def inner_fire(world):
    async with fight(world, hp=5, max_hp=25, favor=0, race="draethar") as call:
        await concentrating(world)
        observed = watch_spend(world)
        with (
            rolls(19),
            patch(
                "check_resolution_save.resolve_saving_throw", wraps=check_resolution_save.resolve_saving_throw
            ) as save,
        ):
            receipt = await call("activate", id="draethar_inner_fire")
        await standing(world, receipt)
        save.assert_called_once()
        assert receipt["hp_remaining"] == 1 and receipt["concentration_broken"] is None
        assert (await row(world, 0))["concentration"]["spell_id"] == "divine_bless"
        assert conditions.has_condition(follower(world).conditions, "blessed")
        spent_projection(observed, world.ids[0])


async def scenario(world, run, *args):
    await run(world, *args)


SCENARIOS = {
    WARD: (
        "patron_zero_hp:trigger_death_ward",
        scenario,
        [(enemy_hit,), (enemy_hit, 15, 2), (enemy_hit, 20), (save_hit,), (inner_fire,), (enemy_hit, 15, 0, True)],
    )
}


@pytest.mark.parametrize(
    "case, hp, damage, remaining",
    [
        ("spent", 5, 10, 0),
        ("aelora", 5, 10, 0),
        ("none", 5, 10, 0),
        ("fallen", 0, 10, 0),
        ("nonlethal", 5, 2, 3),
    ],
)
async def test_ward_only_spends_on_eligible_transitions(world, case, hp, damage, remaining):
    patron = case if case in {"aelora", "none"} else "mortaen"
    gifts = SPENT if case == "spent" else {}
    async with fight(world, hp=hp, max_hp=25, favor=0, patron=patron, gifts=gifts) as call:
        if case == "fallen":
            follower(world).is_fallen = True
        receipt = await hit(world, call, damage=damage)
        target = follower(world)
        assert (target.hp_current, target.is_fallen, target.is_dead) == (remaining, remaining == 0, False)
        assert target.death_save_failures == (2 if case == "fallen" else 0)
        assert "gift_triggered" not in receipt
        assert (await row(world, 0))["patron_gifts"] == gifts


async def test_long_rest_recharges_next_drop(world):
    session = world.ctx.userdata
    session.location_id = "millhaven_inn"
    async with fight(world, hp=5, max_hp=25, favor=0, gifts=SPENT) as call:
        await call("end_combat", outcome="fled")
        for pid in world.ids:
            await world.pool.execute(
                'UPDATE players SET data=data || \'{"location_id":"millhaven_inn"}\'::jsonb WHERE player_id=$1', pid
            )
        recover = game_tools(session, rest)
        assert (await recover("rest", rest_type="short"))["rested"]
        assert (await row(world, 0))["patron_gifts"] == SPENT
        assert (await recover("rest", rest_type="long"))["rested"]
        assert (await row(world, 0))["patron_gifts"][WARD] == {"spent": False}
        await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
        observed = watch_spend(world)
        await standing(world, await hit(world, call, damage=30))
        spent_projection(observed, world.ids[0])


@pytest.mark.parametrize("spent", [False, True])
async def test_held_killing_blow_is_provisional_only_for_ready_ward(world, spent):
    async with fight(world, hp=5, max_hp=25, favor=0, archetype="rogue", gifts=SPENT if spent else {}) as call:
        position(world)
        await declare(world, call, claw(world))
        with rolls(15, 15, damage=10):
            await resolve_until(call, lambda r: (r["next"].get("waiting_on") or {}).get("stage") == "post_roll")
        assert follower(world).hp_current == (await saved_target(world, follower(world))).hp_current == 5
        assert (await row(world, 0))["patron_gifts"] == (SPENT if spent else {})
        held = active(world).held_actions[0]
        assert held["roll"]["attack_result"]["context"] == "killing_blow"
        assert attack_event(world, active(world).get_participant(FOE).name)["context"] == (
            "killing_blow" if spent else ""
        )
        receipt = await resolve_until(call, enemy_damage)
        if spent:
            assert follower(world).is_fallen
        else:
            await standing(world, receipt)


async def test_ward_skips_temporary_hollowed_with_player_row(world):
    async with fight(world, hp=5, max_hp=25, favor=0, guest_class="warrior") as call:
        target = follower(world)
        target.type = "temporary_hollowed"
        guest = world.ids[1]
        active(world).spatial["positions"][guest] = {"x": 5, "y": 0, "z": 0}
        await declare(world, call, attack(guest, target.id))
        with rolls(15, 15):
            receipt = await resolve_until(
                call, lambda r: next((p for p in r["packets"] if p["actor_id"] == guest and "damage" in p), None)
            )
        assert receipt["target_fallen"] and "gift_triggered" not in receipt
        assert WARD not in (await row(world, 0))["patron_gifts"]


async def test_guest_spend_is_visible_while_concentration_is_held(world):
    session = world.ctx.userdata
    async with fight(world, patron="zhael", guest="mortaen", guest_hp=5) as call:
        victim = world.ids[1]
        session.member_state(victim).patron_id = "aelora"
        await concentrating(world, 1)
        observed = watch_spend(world, 1)
        host_gifts = (await row(world, 0))["patron_gifts"]
        position(world)
        await declare(world, call, {**claw(world), "target_id": victim})

        async def keep(offer):
            with session._bind_authenticated_actor(
                world.ids[0], 1, session.multiplayer_owner.lifecycle.require_authorized
            ):
                return await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")

        with rolls(15, 19):
            strike = await resolve_until(call, lambda r: r.get("fate_offer"))
            assert strike["roll_kind"] == "attack"
            paused = await keep(strike)
            offer = paused["fate_offer"]
            assert (offer["roll_kind"], offer["roller_id"]) == ("save", victim)
            assert enemy_damage(paused) is None
            spent_projection(observed, victim)
            assert (await row(world, 0))["patron_gifts"] == host_gifts
            receipt = enemy_damage(await keep(offer))
        await standing(world, receipt, 1)
        spent_projection(observed, victim)


@pytest.mark.parametrize("inner", [False, True], ids=["attack", "inner-fire"])
async def test_ward_spend_and_damage_roll_back_together(world, inner):
    session = world.ctx.userdata
    async with fight(world, hp=5, max_hp=25, favor=0, race="draethar") as call:
        await concentrating(world)
        if not inner:
            position(world)
            await declare(world, call, claw(world))
            await resolve_until(call, lambda _: active(world).held_actions)

        save = db_mutations.save_combat_state

        async def fail(*args, **kwargs):
            await save(*args, **kwargs)
            player, _ = await get_player_at_patron_revision(world.ids[0], conn=kwargs["conn"])
            assert player is not None
            if player["patron_gifts"].get(WARD, {}).get("spent"):
                assert player["hp"]["current"] == 1
                raise RuntimeError("injected after ward write")

        async def land():
            if inner:
                return await call("activate", id="draethar_inner_fire")
            return await resolve_until(call, enemy_damage)

        with patch.object(db_mutations, "save_combat_state", side_effect=fail), rolls(19, 19):
            with pytest.raises(RuntimeError, match="after ward write"):
                for _ in range(12):
                    before = active(world).to_dict()
                    player_before, events_before = await row(world, 0), list(events(world))
                    if inner:
                        await land()
                    else:
                        await call("resolve_phase")
        assert active(world).to_dict() == before
        saved = await db_mutations.load_combat_state(active(world).combat_id, conn=world.pool)
        assert saved is not None and saved.to_dict() == before
        assert await row(world, 0) == player_before and events(world) == events_before
        assert session.concentration.spell_id == "divine_bless"
        with rolls(19, 19):
            await standing(world, await land())


async def test_held_blow_after_this_phase_spent_the_ward_keeps_its_killing_blow(world):
    """The provisional check must see a ward spent earlier in the same phase transaction."""
    async with fight(world, hp=5, max_hp=25, favor=0, archetype="rogue") as call:
        position(world)
        position(world, "mawling_2")
        second = {**attack("mawling_2", world.ids[0]), "action": "Claw"}
        await declare(world, call, claw(world), second)
        dice = []
        with rolls(*[15] * 12, damage=30):
            for _ in range(8):
                result = await call("resolve_phase")
                dice = [e for e in events(world) if e.get("roll_type") == "attack"]
                waiting = (result.get("next") or {}).get("waiting_on") or {} if isinstance(result, dict) else {}
                if len(dice) >= 2 and waiting.get("stage") == "post_roll":
                    break
            else:
                pytest.fail("second attack never held at post_roll")
        assert (await row(world, 0))["patron_gifts"][WARD] == {"spent": True}
        assert follower(world).hp_current == 1
        assert dice[-1]["context"] == "killing_blow"
