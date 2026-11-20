import json
from unittest.mock import patch

import pytest
from _death_ward_fixtures import concentrating
from _mortaen_threshold_fixtures import active, claw, declare, events, fight, position, rolls
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from test_patron_engine_death_ward import WARD, enemy_damage, resolve_until
from test_temp_hp import assert_pools, patch_player

import db_mutations
import db_queries
import event_types as E
import rest_tools


@pytest.mark.parametrize("inner", [False, True], ids=["attack", "inner-fire"])
async def test_temp_hp_and_ward_roll_back_with_the_damage(world, inner):
    await patch_player(world, temp_hp=6)
    session = world.ctx.userdata
    pid = world.ids[0]
    async with fight(world, hp=5, max_hp=25, favor=0, race="draethar") as call:
        await concentrating(world)
        if not inner:
            position(world)
            await declare(world, call, claw(world))
            await resolve_until(call, lambda _: active(world).held_actions)

        save = db_mutations.save_combat_state

        async def fail(combat_id, state, *, conn):
            await save(combat_id, state, conn=conn)
            player = await db_queries.get_player(pid, conn=conn)
            assert player is not None
            if player["patron_gifts"].get(WARD, {}).get("spent"):
                assert (player["hp"]["current"], player["temp_hp"]) == (1, 0)
                pending = await db_mutations.load_combat_state(combat_id, conn=conn)
                assert pending is not None and pending.to_dict() == state
                raise RuntimeError("injected after ward and pool writes")

        with patch.object(db_mutations, "save_combat_state", side_effect=fail), rolls(19, 19, damage=12):
            with pytest.raises(RuntimeError, match="after ward and pool writes"):
                for _ in range(12):
                    before = active(world).to_dict()
                    player_before, events_before = await row(world, 0), list(events(world))
                    if inner:
                        await call("activate", id="draethar_inner_fire")
                    else:
                        await call("resolve_phase")
        assert active(world).to_dict() == before
        saved = await db_mutations.load_combat_state(active(world).combat_id, conn=world.pool)
        assert saved is not None and saved.to_dict() == before
        assert await row(world, 0) == player_before and events(world) == events_before
        assert session.concentration.spell_id == "divine_bless"

        committed = []

        async def published(data, **kwargs):
            event = json.loads(data)
            if event["type"] == E.PATRON_ABILITIES_UPDATED:
                observed = await row(world, 0)
                snapshot = await db_mutations.load_combat_state(active(world).combat_id, conn=world.pool)
                assert snapshot is not None
                target = snapshot.get_participant(pid)
                assert target is not None
                committed.append((kwargs["destination_identities"], observed["temp_hp"], target.temp_hp))

        session.room.local_participant.publish_data.side_effect = published
        with rolls(19, 19, damage=12):
            result = (
                await call("activate", id="draethar_inner_fire") if inner else await resolve_until(call, enemy_damage)
            )
        assert result["gift_triggered"] == "Death Ward" and result["temp_hp_absorbed"] == 6
        await assert_pools(world, 1, 0)
        assert committed == [([pid], 0, 0)]


async def test_long_rest_rolls_back_pool_clear_before_recipient_update(world):
    pid = world.ids[0]
    location = "millhaven_inn"
    session = world.ctx.userdata
    await patch_player(world, temp_hp=6, location_id=location)
    async with fight(world, hp=20, max_hp=30) as call:
        await call("end_combat", outcome="fled")
        session.location_id = location
        recover = game_tools(session, rest_tools.rest)
        before = await row(world, 0), list(events(world))
        lock_increases = rest_tools.lock_increases

        async def fail(player_id, player, *, conn):
            await lock_increases(player_id, player, conn=conn)
            pending = await db_queries.get_player(player_id, conn=conn)
            assert pending is not None and (pending["hp"]["current"], pending["temp_hp"]) == (30, 0)
            raise RuntimeError("injected after rest recovery writes")

        with patch.object(rest_tools, "lock_increases", side_effect=fail):
            with pytest.raises(RuntimeError, match="after rest recovery writes"):
                await recover("rest", rest_type="long")
        assert (await row(world, 0), events(world)) == before and active(world) is None

        committed = []

        async def published(data, **kwargs):
            if json.loads(data)["type"] == E.SESSION_INIT:
                observed = await row(world, 0)
                committed.append((kwargs["destination_identities"], observed["hp"]["current"], observed["temp_hp"]))

        session.room.local_participant.publish_data.side_effect = published
        assert (await recover("rest", rest_type="long"))["rested"]
        assert committed == [([pid], 30, 0)]
