import json
from dataclasses import replace

import pytest
from _dawns_embrace_fixtures import damage_ally, embrace_fight
from _mortaen_threshold_fixtures import (
    ENCOUNTER,
    FOE,
    active,
    attack_event,
    claw,
    declare,
    fight,
    follower,
    position,
    rolls,
)
from _spell_heal_fixtures import WOUNDS
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from test_patron_engine_death_ward import SPENT, WARD, enemy_damage, hit, resolve_until, saved_target
from test_patron_engine_valdris import reload_state
from test_spell_heal_landing import heal_die

import conditions
import db_mutations
import db_queries
import event_types as E
from rest_tools import rest
from session_data import CompanionState


async def patch_player(world, index=0, **fields):
    await world.pool.execute(
        "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", world.ids[index], json.dumps(fields)
    )


async def assert_pools(world, hp, temporary):
    player = await row(world, 0)
    assert (player["hp"]["current"], player["temp_hp"]) == (hp, temporary)
    live = follower(world)
    assert (live.hp_current, live.temp_hp) == (hp, temporary)
    assert await saved_target(world, live) == live


@pytest.mark.parametrize(
    ("damage", "face", "hp", "temporary", "absorbed"),
    [(10, 15, 16, 0, 6), (4, 15, 20, 2, 4), (6, 15, 20, 0, 6), (0, 15, 20, 6, 0), (10, 1, 20, 6, 0)],
)
async def test_enemy_hit_spends_temp_hp_first(world, damage, face, hp, temporary, absorbed):
    await patch_player(world, temp_hp=6)
    async with fight(world, hp=20, max_hp=30) as call:
        receipt = await hit(world, call, damage=damage, face=face)
        await assert_pools(world, hp, temporary)
        if face != 1:
            assert (receipt["temp_hp_absorbed"], receipt["temp_hp_remaining"]) == (absorbed, temporary)
            if absorbed:
                assert f"absorbed {absorbed} damage" in receipt["dm_cue"]


@pytest.mark.parametrize(("damage", "temporary", "context"), [(8, 6, ""), (4, 6, "natural_20"), (16, 6, "")])
async def test_held_hit_previews_without_spending(world, damage, temporary, context):
    await patch_player(world, temp_hp=temporary)
    async with fight(world, hp=3, max_hp=30, archetype="rogue", gifts=SPENT) as call:
        position(world)
        if damage == 16:
            follower(world).damage_affinities = {"resistant": ["slashing"]}
        await declare(world, call, claw(world, damage_type="slashing"))
        face = 20 if context else 15
        with rolls(face, face, damage=damage):
            await resolve_until(call, lambda r: (r["next"].get("waiting_on") or {}).get("stage") == "post_roll")
        event = attack_event(world, active(world).get_participant(FOE).name)
        assert event["damage"] == (8 if damage == 16 else damage * (2 if face == 20 else 1))
        assert event["context"] == context
        await assert_pools(world, 3, temporary)
        await reload_state(world)
        receipt = await resolve_until(call, enemy_damage)
        await assert_pools(world, 1, 0)
        assert receipt["temp_hp_absorbed"] == 6 and not receipt["target_fallen"]


@pytest.mark.parametrize(("intervention", "hp", "pool", "absorbed"), [("dodge", 3, 2, 4), ("inner_fire", 1, 0, 4)])
async def test_reaction_and_live_pool_are_applied_before_landing(world, intervention, hp, pool, absorbed):
    await patch_player(world, temp_hp=6)
    async with fight(world, hp=3, max_hp=30, archetype="rogue", race="draethar", gifts={}) as call:
        position(world)
        await declare(world, call, claw(world))
        with rolls(15, 15, damage=8):
            await resolve_until(call, lambda r: (r["next"].get("waiting_on") or {}).get("stage") == "post_roll")
        await assert_pools(world, 3, 6)
        if intervention == "dodge":
            with world.ctx.userdata._bind_authenticated_actor(world.ids[0], 1, lambda *_: None):
                await call("activate", id="rogue_uncanny_dodge")
        else:
            with rolls(damage=2):
                await call("activate", id="draethar_inner_fire")
        await reload_state(world)
        receipt = await resolve_until(call, enemy_damage)
        await assert_pools(world, hp, pool)
        assert receipt["temp_hp_absorbed"] == absorbed
        gifts = (await row(world, 0))["patron_gifts"]
        assert gifts == ({} if intervention == "dodge" else SPENT)


async def test_companion_does_not_absorb_damage_from_a_player_pool(world):
    world.ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")
    async with embrace_fight(world) as call:
        companion = active(world).get_participant("companion_kael")
        companion.hp_current, companion.hp_max = 20, 30
        companion.temp_hp = 6
        receipt = await damage_ally(world, call, target_id=companion.id, damage=4)
        saved = await saved_target(world, companion)
        assert (saved.hp_current, saved.temp_hp, receipt["temp_hp_absorbed"]) == (16, 0, 0)


async def test_draining_hit_spends_temp_hp_before_ward(world):
    await patch_player(world, temp_hp=6)
    async with fight(world, hp=3, max_hp=30, gifts={}) as call:
        attacker = active(world).get_participant(FOE)
        attacker.hp_current, attacker.hp_max = 10, 30
        receipt = await hit(world, call, damage=12, self_heal="damage_dealt")
        await assert_pools(world, 1, 0)
        assert (await row(world, 0))["patron_gifts"][WARD] == {"spent": True}
        assert not receipt["target_fallen"] and receipt["gift_triggered"] == "Death Ward"
        assert "Mortaen decides" in receipt["dm_cue"] and "absorbed 6 damage" in receipt["dm_cue"]
        assert (receipt["temp_hp_absorbed"], receipt["self_healed"]) == (6, 9)
        assert active(world).get_participant(FOE).hp_current == (await saved_target(world, attacker)).hp_current == 19


@pytest.mark.parametrize(("damage", "dies"), [(33, False), (39, True)])
async def test_overkill_excludes_absorbed_damage(world, damage, dies):
    await patch_player(world, temp_hp=6)
    async with fight(world, hp=3, max_hp=30, gifts=SPENT) as call:
        await hit(world, call, damage=damage)
        assert follower(world).is_fallen and follower(world).is_dead is dies
        await assert_pools(world, 0, 0)


@pytest.mark.parametrize("inner", [False, True], ids=["attack", "inner-fire"])
async def test_hollowed_rise_persists_spent_pool_without_echo_hp(world, inner):
    await patch_player(world, temp_hp=6)
    hollowed = conditions.apply_condition([], "hollowed")[0] | {"stage": 2}
    async with fight(world, hp=3, max_hp=30, gifts=SPENT, race="draethar", conditions=[hollowed]) as call:
        if inner:
            with rolls(damage=12):
                receipt = await call("activate", id="draethar_inner_fire")
            rose = receipt["rose_hollowed"]
        else:
            receipt = await hit(world, call, damage=12)
            rose = receipt["target_rose_hollowed"]
        assert rose and follower(world).hp_current == 15
        player = await row(world, 0)
        assert (player["hp"]["current"], player["temp_hp"]) == (3, 0)
        assert (await saved_target(world, follower(world))).temp_hp == 0


async def test_no_stack_grant(world):
    from temp_hp import grant

    await patch_player(world, temp_hp=8)
    async with fight(world, hp=20, max_hp=30):
        async with world.db.transaction() as conn:
            player = (await db_queries.get_players_for_update([world.ids[0]], conn=conn))[world.ids[0]]
            assert await grant(world.ids[0], player, 5, participant=follower(world), conn=conn) == (8, 8)
        assert (await row(world, 0))["temp_hp"] == follower(world).temp_hp == 8
        async with world.db.transaction() as conn:
            player = (await db_queries.get_players_for_update([world.ids[0]], conn=conn))[world.ids[0]]
            foe = replace(active(world).get_participant(FOE), id=world.ids[0])
            other_player = active(world).get_participant(world.ids[1])
            for invalid in (foe, other_player):
                with pytest.raises(ValueError, match="player"):
                    await grant(world.ids[0], player, 11, participant=invalid, conn=conn)
        assert (await row(world, 0))["temp_hp"] == 8


@pytest.mark.parametrize("combat", [False, True])
async def test_healing_preserves_temp_hp(healer, combat):
    await healer.prepare(WOUNDS)
    ally = await healer.add_player()
    await healer.patch_row(ally, temp_hp=6)
    if combat:
        await healer.fight()
        healer.sd.combat_state.get_participant(ally).temp_hp = 6
        await healer.save()
    with heal_die(5):
        packet = await healer.cast(WOUNDS, targets=[ally], combat=combat)
    current = packet["healing_results"][0]["hp_current"]
    player = await healer.read(ally)
    assert current > 3 and (player["hp"]["current"], player["temp_hp"]) == (current, 6)
    if combat:
        target = (await healer.checkpoint()).get_participant(ally)
        assert (target.hp_current, target.temp_hp) == (current, 6)


async def test_pool_survives_encounters_until_long_rest(world):
    await patch_player(world, temp_hp=6, location_id="millhaven_inn")
    await patch_player(world, 1, temp_hp=8, location_id="accord_guild_hall")
    session = world.ctx.userdata
    async with fight(world, hp=30, max_hp=30) as call:
        await hit(world, call, damage=4)
        await assert_pools(world, 30, 2)
        await reload_state(world)
        await call("end_combat", outcome="fled")
        await call("enter_mode", mode="combat", encounter_id=ENCOUNTER)
        await assert_pools(world, 30, 2)
        await call("end_combat", outcome="fled")
        session.location_id = "millhaven_inn"
        recover = game_tools(session, rest)
        await recover("rest", rest_type="short")
        assert (await row(world, 0))["temp_hp"] == 2
        await recover("rest", rest_type="long")
        assert (await row(world, 0))["temp_hp"] == 0
        assert (await row(world, 1))["temp_hp"] == 8


async def test_legacy_pool_defaults_to_zero_on_entry_and_reload(world):
    async with fight(world, hp=20, max_hp=30):
        assert follower(world).temp_hp == 0
        snapshot = active(world).to_dict()
        for participant in snapshot["participants"]:
            del participant["temp_hp"]
        await db_mutations.save_combat_state(snapshot["combat_id"], snapshot, conn=world.pool)
        await reload_state(world)
        assert follower(world).temp_hp == 0


async def test_inner_fire_spends_temp_hp(world):
    await patch_player(world, temp_hp=6)
    async with fight(world, hp=20, max_hp=30, race="draethar") as call:
        observed = []

        async def published(data, **_):
            event = json.loads(data)
            if event["type"] == E.COMBAT_UI_UPDATE:
                target = next(p for p in event["combatants"] if p["id"] == world.ids[0])
                saved = await saved_target(world, follower(world))
                observed.append((target["hpCurrent"], (await row(world, 0))["temp_hp"], saved.temp_hp))

        world.ctx.userdata.room.local_participant.publish_data.side_effect = published
        with rolls(damage=4):
            receipt = await call("activate", id="draethar_inner_fire")
        await assert_pools(world, 20, 2)
        assert observed == [(20, 2, 2)]
        assert (receipt["fire_damage"], receipt["hp_remaining"], receipt["temp_hp_absorbed"]) == (4, 20, 4)
        assert "absorbed 4 damage" in receipt["dm_cue"]
