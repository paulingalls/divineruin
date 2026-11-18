"""Drive Acknowledged passives through the engine registry scenarios."""

from datetime import datetime, timedelta
from unittest.mock import patch

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20
from acceptance.test_kaelen_iron_resolve_capstone import required_player, ui_player
from test_favor_decay_hydration import _mods

import db_content_queries
import db_mutations
import db_queries
from check_tools import check
from combat_turn import declare_phase, resolve_phase
from conditions import apply_condition, has_condition
from db_session_queries import get_session_init_payload
from hp_scaling import calculate_max_hp
from mode_tools import enter_mode
from progression_tools import _award_divine_favor_core, _award_xp_core
from rules_engine import XP_FOR_LEVEL
from scene_tools import enter_location
from session_data import SessionData
from session_hydration import hydrate_session_state

ENCOUNTER = "hollowed_scout"
ENEMY = "hollowed_scout_1"


def favor(patron):
    return {"patron": patron, "level": 0, "max": 100, "last_whisper_level": 0}


async def ward_check(world, patron, effect, save, condition, expected, dice_count):
    await configure(
        world,
        patron,
        "mage",
        index=0,
        divine_favor=favor(patron),
        conditions=apply_condition([], condition, source="test") if condition else [],
    )
    call = game_tools(world.ctx.userdata, check)
    with patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(17)]) as dice:
        result = await call("check", roll={"kind": "save", "save_type": save, "dc": 12, "effect_on_fail": effect})
    assert result["roll"] == expected and dice.call_count == dice_count
    assert (result["outcome"] == "success") is (expected == 17)


async def ward_combat(world, patron, damage, item=False):
    pid, guest = world.ids
    await configure(
        world, patron, "mage", divine_favor=favor(patron), hp={"current": 30, "max": 30}, conditions=[], speed=30
    )
    await configure(world, "none", "mage", index=1, speed=30)
    if item:
        await db_mutations.add_inventory_item(pid, "stillheart", 1, tainted=False, conn=world.pool)
    session = world.ctx.userdata
    call = game_tools(session, enter_mode, declare_phase, resolve_phase)
    load_enemy = db_content_queries.load_creature_enemy

    async def load_with_hollowed_action(*args, **kwargs):
        enemy = await load_enemy(*args, **kwargs)
        action = {
            "name": "Hollow touch",
            "applies_condition": "hollowed",
            "save": "wisdom" if item else "constitution",
            "dc": 12,
            "reach": 60,
            "type": "ranged",
        }
        if damage:
            action.update(half_on_success=True, damage="1d4", damage_type="necrotic")
        return {**enemy, "action_pool": [action]}

    with patch.object(db_content_queries, "load_creature_enemy", side_effect=load_with_hollowed_action):
        await call("enter_mode", mode="combat", encounter_id=ENCOUNTER)
    combat_id = session.combat_state.combat_id
    try:
        session.combat_state = await db_mutations.load_combat_state(combat_id)
        await call(
            "declare_phase",
            declarations=[
                defend(pid),
                defend(guest),
                {**attack(ENEMY, pid), "action": "Hollow touch"},
            ],
        )
        await call("resolve_phase")
        window = (await call("resolve_phase"))["next"]["waiting_on"]
        assert window["stage"] == "pre_roll" and window["actor_id"] == ENEMY
        with patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(17)]) as dice:
            result = await call("resolve_phase")
        packets = [p for p in result["packets"] if "save_success" in p]
        assert len(packets) == 1, result["packets"]
        packet = packets[0]
        protected = patron == "veythar" or item
        if item:
            assert packet["save_advantage_source"] == "Stillheart"
        assert packet["save_success"] is protected and dice.call_count == (2 if protected else 1)
        saved = await db_mutations.load_combat_state(combat_id)
        assert has_condition(required_player(saved, pid).conditions, "hollowed") is (not protected)
    finally:
        await db_mutations.delete_combat_state(combat_id)


async def endurance(world):
    host, guest = world.ids
    session = world.ctx.userdata
    base = calculate_max_hp("warrior", 3, 0)
    stored = {"current": base + 3, "max": base}
    await configure(world, "veythar", "mage", hp={"current": 15, "max": 15}, speed=30)
    await configure(
        world,
        "kaelen",
        "warrior",
        index=1,
        level=3,
        xp=XP_FOR_LEVEL[3],
        attributes={"constitution": 10},
        hp=stored,
        maxhp_override=-7,
        speed=30,
        divine_favor=favor("kaelen"),
    )
    call = game_tools(session, enter_location, enter_mode)
    for level in (0, 40, 35):
        initial = await get_session_init_payload(guest)
        assert initial["character"]["hp"] == {"current": base + 3, "max": base + 5}
        assert initial["character"]["divine_favor"]["level"] == level
        with session._bind_authenticated_actor(guest, 1, lambda *_: None):
            summary = (await call("enter_location", location_id=session.location_id))["player"]
        assert (summary["hp_current"], summary["hp_max"]) == (base + 3, base + 5)
        if level == 0:
            async with world.db.transaction() as conn:
                await _award_divine_favor_core(guest, 40, "served", conn=conn, pending_events=[])
        elif level == 40:
            follower = await row(world)
            reconnect = SessionData(player_id=guest, location_id=session.location_id)
            served_at = follower["divine_favor"]["last_served_at"]
            now = datetime.fromisoformat(served_at) + timedelta(days=8)
            await hydrate_session_state(reconnect, follower, conn=world.pool, now=now, **_mods())
    await call("enter_mode", mode="combat", encounter_id=ENCOUNTER)
    combat_id = session.combat_state.combat_id
    try:
        saved = await db_mutations.load_combat_state(combat_id)
        assert required_player(saved, host).hp_max == 15
        guest_combatant = required_player(saved, guest)
        assert (guest_combatant.hp_current, guest_combatant.hp_max) == (base + 3, base + 5)
        guest_ui = ui_player(world.ctx, guest)
        assert (guest_ui["hpCurrent"], guest_ui["hpMax"]) == (base + 3, base + 5)
        assert (await row(world))["hp"] == stored
    finally:
        await db_mutations.delete_combat_state(combat_id)
    session.combat_state = None
    for amount, level in [(XP_FOR_LEVEL[4] - XP_FOR_LEVEL[3], 4), (1, 4)]:
        async with world.db.transaction() as conn:
            locked = await db_queries.get_player(guest, conn=conn, for_update=True)
            assert locked is not None
            await _award_xp_core(
                player_id=guest, player=locked, amount=amount, reason="earned", conn=conn, pending_events=[]
            )
        initial = await get_session_init_payload(guest)
        assert initial["character"]["level"] == level
        assert initial["character"]["hp"] == {"current": base + 3, "max": base + 5}
        assert (await row(world))["hp"] == stored


async def ward(world, boundary, *args):
    await boundary(world, *args)


SCENARIOS = {
    "veythar_scholars_ward": (
        "patron_passives:scholars_ward",
        ward,
        [
            (ward_check, "veythar", " Hollowed ", "constitution", None, 17, 2),
            (ward_check, "kaelen", "hollowed", "constitution", None, 5, 1),
            (ward_check, "none", "hollowed", "constitution", None, 5, 1),
            (ward_check, "veythar", "temporary_hollowed", "constitution", None, 5, 1),
            (ward_check, "veythar", "hollowed", "wisdom", "hollowed", 5, 1),
            (ward_check, "veythar", "hollowed", "strength", "stunned", 0, 0),
            (ward_combat, "veythar", False),
            (ward_combat, "kaelen", False),
            (ward_combat, "veythar", True),
            (ward_combat, "kaelen", True),
            (ward_combat, "veythar", False, True),
            (ward_combat, "kaelen", False, True),
        ],
    ),
    "kaelen_warriors_endurance": ("patron_passives:warriors_endurance", endurance, [()]),
}
