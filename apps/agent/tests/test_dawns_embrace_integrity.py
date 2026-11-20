from unittest.mock import patch

import pytest
from _dawns_embrace_fixtures import EMBRACE, SPENT, aim, damage_ally, embrace_fight
from _mortaen_threshold_fixtures import FOE, active, attack_event, declare, rolls
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack
from test_patron_engine_death_ward import resolve_until

import combat_hold
import db_mutations
import db_queries
import patron_zero_hp


@pytest.mark.parametrize("case", ["absent", "patron", "tier", "spent", "already-zero", "nonlethal", "hollowed"])
async def test_ineligible_damage_does_not_spend(world, case):
    async with embrace_fight(
        world,
        favor=74 if case == "tier" else 75,
        gifts=SPENT if case == "spent" else {},
        donor_patron="aelora" if case == "patron" else "orenthel",
    ) as call:
        session = world.ctx.userdata
        donor_id = world.ids[1]
        donor = active(world).get_participant(donor_id)
        target = active(world).get_participant(world.ids[0])
        if case == "absent":
            session.multiplayer_owner.lifecycle.mark_departed(donor_id)
            assert donor_id in session.party.member_ids and donor_id not in session.present_member_ids
        elif case == "already-zero":
            target.hp_current = 0
            target.is_fallen = True
        elif case == "hollowed":
            donor.type = "temporary_hollowed"
        receipt = await damage_ally(world, call, inner=True, damage=2 if case == "nonlethal" else 10)
        assert "gift_triggered" not in receipt
        assert receipt["hp_remaining"] == (2 if case == "nonlethal" else 0)
        assert (await row(world))["patron_gifts"] == (SPENT if case == "spent" else {})


@pytest.mark.parametrize("kind", ["enemy", "temporary_hollowed"])
async def test_damage_does_not_catch_hostile_targets(world, kind):
    async with embrace_fight(world, patron="orenthel", favor=75 if kind == "temporary_hollowed" else 40) as call:
        state = active(world)
        host_id, donor_id = world.ids
        await world.pool.execute(
            """UPDATE players SET data = jsonb_set(data, '{divine_favor,level}', '75') WHERE player_id = $1""",
            host_id,
        )
        if kind == "enemy":
            actor_id, target_id = host_id, FOE
        else:
            actor_id, target_id = donor_id, host_id
        target = state.get_participant(target_id)
        target.type, target.hp_current, target.ac = kind, 4, 1
        state.spatial["positions"][target_id] = {"x": 5, "y": 0, "z": 0}
        state.spatial["positions"][actor_id] = {"x": 0, "y": 0, "z": 0}
        await declare(world, call, attack(actor_id, target_id))
        with rolls(15, 15):
            result = await resolve_until(
                call, lambda r: next((p for p in r["packets"] if p["actor_id"] == actor_id and "damage" in p), None)
            )
        assert result["target_fallen"] and "gift_triggered" not in result
        assert all(EMBRACE not in player["patron_gifts"] for player in (await row(world, 0), await row(world)))


@pytest.mark.parametrize("death", ["instant", "failed-saves"])
async def test_terminal_donor_cannot_spend(world, death):
    async with embrace_fight(world) as call:
        state = active(world)
        ally_id, donor_id = world.ids
        donor = state.get_participant(donor_id)
        if death == "instant":
            donor.hp_max = 1
            donor.hp_current = 1
        else:
            donor.hp_current = 0
            donor.is_fallen = True
            donor.death_save_failures = 2
        for participant in state.participants:
            participant.reaction_ids = []
        await aim(world, call, donor_id, ally_id)
        with rolls(*[15] * 12):
            receipt = await resolve_until(
                call, lambda r: next((p for p in r["packets"] if p["actor_id"] == "mawling_2" and "damage" in p), None)
            )
        donor = active(world).get_participant(donor_id)
        assert donor.is_dead if death == "instant" else donor.death_save_failures == 3
        assert receipt["target_fallen"] and "gift_triggered" not in receipt
        assert not (await row(world))["patron_gifts"]


@pytest.mark.parametrize("spent", [False, True], ids=["ready", "spent"])
async def test_held_preview_preserves_spend(world, spent):
    async with embrace_fight(world, archetype="rogue", gifts=SPENT if spent else {}) as call:
        await aim(world, call, world.ids[0])
        build = combat_hold.build_attack_dice_roll_payload
        with rolls(15, 15), patch.object(combat_hold, "build_attack_dice_roll_payload", wraps=build) as preview:
            await resolve_until(call, lambda r: (r["next"].get("waiting_on") or {}).get("stage") == "post_roll")
        assert preview.call_args.args[1].target_hp_remaining == (0 if spent else 10)
        state = active(world)
        assert state.get_participant(world.ids[0]).hp_current == 4
        assert state.held_actions[0]["roll"]["attack_result"]["context"] == "killing_blow"
        assert attack_event(world, state.get_participant(FOE).name)["context"] == ("killing_blow" if spent else "")
        assert (await row(world))["patron_gifts"] == (SPENT if spent else {})


@pytest.mark.parametrize("inner", [False, True], ids=["attack", "inner-fire"])
async def test_writers_lock_damage_rows_and_roll_back_together(world, inner):
    async with embrace_fight(world) as call:
        if not inner:
            await aim(world, call, world.ids[0])
            await resolve_until(call, lambda _: active(world).held_actions)
        save = db_mutations.save_combat_state
        lock = db_queries.get_players_for_update
        get_player = db_queries.get_player
        spend = patron_zero_hp.write_state
        locked = []
        batch_connections = []

        async def write(player_id, data, *, gift_id, conn):
            assert batch_connections.count(conn) == 1 and conn is locked[-1][0]
            await spend(player_id, data, gift_id=gift_id, conn=conn)

        async def batch(ids, *, conn):
            assert ids == sorted(world.ids) and conn.is_in_transaction()
            locked.append((conn, await lock(ids, conn=conn)))
            batch_connections.append(conn)
            return locked[-1][1]

        async def read(player_id, *, conn=None, for_update=False):
            if for_update and player_id == world.ids[0]:
                assert any(connection is conn for connection, _ in locked)
            return await get_player(player_id, conn=conn, for_update=for_update)

        async def fail(combat_id, data, *, conn):
            await save(combat_id, data, conn=conn)
            donor = await get_player(world.ids[1], conn=conn)
            assert donor is not None
            if donor["patron_gifts"].get(EMBRACE, {}).get("spent"):
                assert locked and locked[-1][0] is conn
                ally = await get_player(world.ids[0], conn=conn)
                assert ally is not None and ally["hp"]["current"] == 10
                raise RuntimeError("after embrace and damage writes")

        with (
            patch.object(db_mutations, "save_combat_state", side_effect=fail),
            patch.object(patron_zero_hp, "write_state", side_effect=write),
            patch.object(db_queries, "get_players_for_update", side_effect=batch),
            patch.object(db_queries, "get_player", side_effect=read),
            rolls(19, 19),
            pytest.raises(RuntimeError, match="after embrace and damage writes"),
        ):
            for _ in range(12):
                before = active(world).to_dict()
                if inner:
                    await call("activate", id="draethar_inner_fire")
                else:
                    await call("resolve_phase")
        assert active(world).to_dict() == before
        assert (await row(world, 0))["hp"]["current"] == 4
        assert not (await row(world))["patron_gifts"]
