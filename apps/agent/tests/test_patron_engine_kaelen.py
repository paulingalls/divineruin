import json
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import encounter, row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import (
    _build_state,
    _d20,
    _damage_die,
    _declare_attacks,
    _enemy,
    _player,
    _resolve_round,
    _start_combat,
)
from acceptance.seeds import seed_player_with_pools
from acceptance.test_kaelen_iron_resolve_capstone import required_player, ui_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room, published_payloads
from voice_condition_fixtures import place_actors

import db_mutations
from activate_tools import _activate_impl, activate
from check_tools import check
from combat_end import end_combat
from combat_turn import declare_phase, resolve_phase
from mode_tools import enter_mode
from query_tools import query_info
from session_data import CompanionState


async def iron_resolve_through_enemy_attack(world, archetype, before, damage, fires):
    dev_db_pool = world.pool
    pid = f"synergy_iron_{archetype}_{before}_{damage}"
    state = _build_state(f"combat_{pid}", pid, [_enemy("goblin_a", hp=100)])
    pc = required_player(state, pid)
    pc.hp_current, pc.hp_max = before, 100
    ctx = make_context(pid, room=make_mock_room())
    ctx.userdata.party.primary.patron_id = "kaelen"
    try:
        await _start_combat(dev_db_pool, pid, state, ctx)
        await dev_db_pool.execute(
            "UPDATE players SET data=data || $2::jsonb WHERE player_id=$1",
            pid,
            json.dumps(
                {"class": archetype, "hp": {"current": before, "max": 100}, "divine_favor": {"patron": "kaelen"}}
            ),
        )
        await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
        with (
            patch("check_resolution.dice_roll", return_value=_d20(15)),
            patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
        ):
            result = await _resolve_round(ctx)
        packet = next(p for p in result["packets"] if p.get("attacker") == "Goblin A")
        live = required_player(ctx.userdata.combat_state, pid)
        assert live.hp_current == before - damage
        assert (packet.get("gift_triggered") == "Iron Resolve") is fires
        assert live.iron_resolve_spent is fires
        saved = await db_mutations.load_combat_state(state.combat_id, conn=dev_db_pool)
        assert required_player(saved, pid).iron_resolve_spent is fires
        assert [c["type"] for c in ui_player(ctx, pid)["conditions"]] == [c["type"] for c in live.conditions]
        if fires:
            assert live.conditions[0]["type"] == "iron_resolve"
            assert live.conditions[0]["duration"] == 1
        if (archetype, before, damage) == ("warrior", 50, 15):
            ctx.userdata.combat_state = saved
            required_player(saved, pid).hp_current = 50
            await db_mutations.update_player_hp(pid, 50, conn=dev_db_pool)
            await _declare_attacks(ctx, pid, "goblin_a", ["goblin_a"])
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
            ):
                again = await _resolve_round(ctx)
            enemy = next(p for p in again["packets"] if p.get("attacker") == "Goblin A")
            assert "gift_triggered" not in enemy
            assert required_player(ctx.userdata.combat_state, pid).conditions == []
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=dev_db_pool)
        await dev_db_pool.execute("DELETE FROM players WHERE player_id=$1", pid)


@pytest.mark.parametrize("archetype,fires", [("warrior", True), ("bard", False)])
async def test_inner_fire_uses_locked_archetype(world, archetype, fires):
    w = world
    await configure(w, "kaelen", archetype, race="draethar", hp={"current": 10, "max": 20})
    encounter(w)
    w.ctx.userdata.combat_state.participants[0].hp_current = 10
    import draethar_inner_fire

    with (
        patch.object(draethar_inner_fire.db, "transaction", w.db.transaction),
        patch("draethar_inner_fire.dice.roll", return_value=_damage_die(3)),
    ):
        packet = json.loads(await _activate_impl(w.ctx, "draethar_inner_fire"))
    assert (packet.get("gift_triggered") == "Iron Resolve") is fires
    assert (await row(w, 0))["hp"]["current"] == 7


async def test_guest_damage_reads_latest_target_class(world):
    import combat_turn

    w = world
    for host_class, guest_class, fires in [("bard", "warrior", True), ("warrior", "bard", False)]:
        await configure(w, "kaelen", host_class)
        await configure(w, "kaelen", guest_class, index=1)
        encounter(w)
        state = w.ctx.userdata.combat_state
        state.combat_id = "synergy_guest_" + guest_class
        guest = state.get_participant(w.ids[1])
        guest.hp_current, guest.hp_max = 50, 100
        state.participants.append(_enemy("goblin_a", hp=100))
        state.initiative_order = [*w.ids, "goblin_a"]
        place_actors(state)
        try:
            await combat_turn._declare_phase_impl(
                w.ctx,
                {
                    w.ids[0]: {"type": "defend"},
                    w.ids[1]: {"type": "defend"},
                    "goblin_a": {"type": "attack", "action": "Scimitar", "target_id": w.ids[1]},
                },
            )
            with (
                patch("check_resolution.dice_roll", return_value=_d20(15)),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(15)),
            ):
                await _resolve_round(w.ctx)
            live = required_player(w.ctx.userdata.combat_state, w.ids[1])
            assert live.hp_current == 35 and live.iron_resolve_spent is fires
            assert not required_player(w.ctx.userdata.combat_state, w.ids[0]).iron_resolve_spent
        finally:
            await db_mutations.delete_combat_state(state.combat_id, conn=w.pool)


BATTLE_CRY = "kaelen_battle_cry_of_the_ironhand"
CRY_GIFTS = {"kaelen_kaelens_judgment": {"spent": True}}
COMPANION = "companion_kael"


async def battle_cry_setup(world, *, favor=40, patron_gifts=CRY_GIFTS, foe_hp=100, other_enemies=()):
    session = world.ctx.userdata
    session.companion = CompanionState(id=COMPANION, name="Kael")
    foe = _enemy("foe", hp=foe_hp)
    foe.ac = 13
    state = _build_state(world.ids[0], world.ids[0], [foe])
    host, foe = state.participants
    guest, companion = _player(world.ids[1]), _player(COMPANION)
    allies = [host, guest, companion]
    state.participants = [*allies, foe, *other_enemies]
    state.initiative_order = [p.id for p in state.participants]
    for p, name, strength, mod in zip(allies, ("Rook", "Iris", "Kael"), (14, 12, 16), (0, 1, -1), strict=True):
        p.name, p.attributes, p.level, p.attack_mod = name, {"strength": strength}, 2, mod
    companion.type = "companion"
    host.enhancers = ["extra_attack"]
    for index, (p, patron) in enumerate(((host, "kaelen"), (guest, "veythar"))):
        await seed_player_with_pools(world.pool, player_id=p.id, class_="warrior")
        await configure(
            world,
            patron,
            "warrior",
            index=index,
            name=p.name,
            attributes=p.attributes,
            equipment={"main_hand": p.action_pool[0]},
            patron_gifts=patron_gifts if index == 0 else {},
            divine_favor={"patron": patron, "level": favor, "max": 100},
        )
    place_actors(state)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)
    session.combat_state = state
    return game_tools(session, activate, query_info, declare_phase, resolve_phase, end_combat, enter_mode, check)


def cry_conditions(state):
    assert state is not None
    return {p.id: [c for c in p.conditions if c["type"] == "battle_cry"] for p in state.participants}


def cry_projection(packet):
    return next(a for a in packet["abilities"] if a["id"] == BATTLE_CRY)


async def cry_round(world, call, foe_id, expected, *, buffed=False):
    session = world.ctx.userdata
    state = session.combat_state
    assert state is not None
    room = session.room
    initial = len(published_payloads(room))
    await call(
        "declare_phase", declarations=[attack(p.id, foe_id) if p.is_ally else defend(p.id) for p in state.participants]
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(9)),
        patch("condition_bonus.dice_roll", return_value=_damage_die(3)) as bonus,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(1)),
    ):
        for _ in range(5):
            await call("resolve_phase")
            if session.combat_state.beat == "declaration":
                break
        assert session.combat_state.round_number == state.round_number + 1
    events = [e for e in published_payloads(room)[initial:] if e["type"] == "dice_roll" and e["roll_type"] == "attack"]
    assert {name: [e["total"] for e in events if e["attacker"] == name] for name in expected} == expected
    assert len(events) == sum(map(len, expected.values()))
    assert [c.args[0] for c in bonus.call_args_list] == (["1d4"] * len(events) if buffed else [])
    return events


async def battle_cry_scenario(world, early_end):
    call = await battle_cry_setup(world)
    session = world.ctx.userdata
    combat_id = session.combat_state.combat_id
    allies = dict(zip([*world.ids, COMPANION], ["Rook", "Iris", "Kael"], strict=True))
    try:
        projected = cry_projection(await call("query_info", kind="patron"))
        assert (projected["available"], projected["spent"], projected["tier"]) == (True, False, "Devoted")
        result = await call("activate", id=projected["id"])
        assert {a["id"]: a["name"] for a in result["allies"]} == allies
        expected = {
            pid: [{"type": "battle_cry", "source": world.ids[0], "duration": 2, "stacks": 1}] if pid in allies else []
            for pid in [*allies, "foe"]
        }
        assert cry_conditions(session.combat_state) == expected
        for pid in allies:
            assert ui_player(world.ctx, pid)["conditions"] == [
                {"type": "battle_cry", "source": world.ids[0], "stacks": 1}
            ]
        assert cry_conditions(await db_mutations.load_combat_state(combat_id, conn=world.pool)) == expected
        assert (await row(world, 0))["patron_gifts"] == {**CRY_GIFTS, BATTLE_CRY: {"spent": True}}
        spent = cry_projection(await call("query_info", kind="patron"))
        assert (spent["available"], spent["spent"], spent["reason"]) == (
            False,
            True,
            "Already spent; requires a long rest to restore it.",
        )
        if early_end:
            await call("end_combat", outcome="fled")
            for i in range(2):
                assert all(c["type"] != "battle_cry" for c in (await row(world, i)).get("conditions", []))
            await call("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
            state = session.combat_state
            combat_id = state.combat_id
            assert not any(cry_conditions(state).values())
            # Keep the loaded roster and conditions, with every melee combatant in reach.
            place_actors(state)
            await cry_round(world, call, "mawling_1", {"Rook": [12], "Iris": [11], "Kael": [12]})
        else:
            with (
                patch("check_resolution.dice_roll", return_value=_d20(9)),
                patch("condition_bonus.dice_roll", return_value=_damage_die(3)) as bonus,
            ):
                save = await call(
                    "check", roll={"kind": "save", "save_type": "dexterity", "dc": 12, "effect_on_fail": "Stumble"}
                )
                assert (save["total"], save["outcome"]) == (10, "failure")
                bonus.assert_not_called()
                skill = await call(
                    "check",
                    roll={
                        "kind": "skill",
                        "skill": "athletics",
                        "difficulty": "moderate",
                        "context_description": "Shift a fallen beam",
                        "hearing_only": False,
                    },
                )
                assert (skill["total"], skill["outcome"]) == (11, "failure")
                bonus.assert_not_called()

            # Each ally has +3 before Battle Cry. Defend raises the foe's AC from 13 to 15.
            buffed = {"Rook": [15, 15], "Iris": [15], "Kael": [15]}
            for duration in (1, 0):
                events = await cry_round(world, call, "foe", buffed, buffed=True)
                assert all(e["success"] for e in events)
                assert cry_conditions(session.combat_state) == {
                    pid: [{**c, "duration": duration} for c in buffs] if duration else []
                    for pid, buffs in expected.items()
                }
            events = await cry_round(world, call, "foe", {"Rook": [12, 12], "Iris": [12], "Kael": [12]})
            assert not any(e["success"] for e in events)
    finally:
        await db_mutations.delete_combat_state(combat_id, conn=world.pool)


@pytest.mark.parametrize(
    "case,reason",
    [
        ("outside", "in combat"),
        ("absent", "player participant"),
        ("tier", "Devoted"),
        ("patron", "follower of kaelen"),
        ("spent", "Already spent"),
    ],
)
async def test_battle_cry_refuses_without_writes(world, case, reason):
    call = await battle_cry_setup(world)
    session = world.ctx.userdata
    state = session.combat_state
    try:
        if case == "outside":
            session.combat_state = None
        elif case == "absent":
            state.participants = state.participants[1:]
            state.initiative_order = state.initiative_order[1:]
            place_actors(state)
            await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=world.pool)
        elif case == "tier":
            await configure(world, "kaelen", "warrior", divine_favor={"patron": "kaelen", "level": 24, "max": 100})
        elif case == "patron":
            await configure(world, "veythar", "warrior")
        elif case == "spent":
            await call("activate", id=BATTLE_CRY)
        saved = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
        live = session.combat_state.to_dict() if session.combat_state else None
        gifts = (await row(world, 0))["patron_gifts"]
        events = published_payloads(session.room)
        with pytest.raises(ToolError, match=reason):
            await call("activate", id=BATTLE_CRY)
        assert (await row(world, 0))["patron_gifts"] == gifts
        assert await db_mutations.load_combat_state(state.combat_id, conn=world.pool) == saved
        assert (session.combat_state.to_dict() if session.combat_state else None) == live
        assert published_payloads(session.room) == events
    finally:
        await db_mutations.delete_combat_state(state.combat_id, conn=world.pool)


SCENARIOS = {
    BATTLE_CRY: ("patron_combat_edges:battle_cry", battle_cry_scenario, [(False,), (True,)]),
    "kaelen_iron_resolve": (
        "kaelen_gift:trigger_iron_resolve",
        iron_resolve_through_enemy_attack,
        [("bard", 30, 10, True), ("bard", 30, 5, False)],
    ),
    "kaelen_tempered_resolve": (
        "kaelen_gift:trigger_iron_resolve",
        iron_resolve_through_enemy_attack,
        [
            ("warrior", 50, 15, True),
            ("guardian", 50, 15, True),
            ("skirmisher", 50, 15, True),
            ("bard", 50, 15, False),
            ("warrior", 40, 5, True),
            ("warrior", 50, 10, False),
            ("warrior", 35, 5, False),
            ("warrior", 50, 50, False),
        ],
    ),
}


def test_battle_cry_skips_dead_allies():
    from patron_combat_edges import battle_cry

    living, dead = _player("living"), _player("dead")
    dead.is_dead = True
    state = _build_state("living", "living", [_enemy("foe", hp=10)])
    state.participants = [living, dead, *state.participants[1:]]
    updated, result = battle_cry(state, "living", target_id=None)
    assert [a["id"] for a in result["allies"]] == ["living"]
    corpse = updated.get_participant("dead")
    assert corpse is not None and corpse.conditions == []
