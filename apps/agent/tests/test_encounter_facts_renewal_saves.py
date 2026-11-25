"""Terminal death saves and racial self-damage at the registered tools."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance._capstone_helpers import _d20, _player
from combat.test_handle_hp_zero import _hollowed
from test_encounter_facts_damage import GOBLIN, OTHER, fight, goblin_strike
from test_encounter_facts_heal import save
from test_encounter_facts_renewal import focus, receipt, renewals, rollback, setup_recipient
from voice_condition_fixtures import participant, place_actors

import db_mutations
from combat_death_save import request_death_save
from patron_passives import effective_hp
from session_data import CompanionState


async def test_third_failed_save_awards_once_and_stabilization_awards_nothing(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="warden") as f:
        await setup_recipient(world, "warden")
        await f.round(goblin_strike(GOBLIN, f.ally))
        call = game_tools(f.session, request_death_save)
        for _ in range(2):
            assert not (await save(call, f.ally, 5))["dead"]
        third = await save(call, f.ally, 5)
        assert third["dead"] and third["total_failures"] == 3
        assert third.get("focus_renewals") == [receipt(f.hero, f.ally, 3, 5)]
        assert participant(await f.reload(), f.ally).death_save_failures == 3
        repeated = await save(call, f.ally, 5)
        assert repeated["dead"] and repeated["total_failures"] == 4
        assert "focus_renewals" not in repeated
        ally = participant(await f.reload(), f.ally)
        ally.death_save_failures, ally.death_save_successes = 0, 2
        stable = await save(call, f.ally, 15)
        assert stable["stabilized"] and "focus_renewals" not in stable
        assert await focus(world) == 5


@pytest.mark.parametrize("producer", ["save", "damage", "instant", "player_damage"])
async def test_fallen_damage_and_companion_protection(world: SimpleNamespace, producer: str) -> None:
    async with fight(world, "mortaen", archetype="warden", goblin_hp=5) as f:
        await setup_recipient(world, "warden")
        state = f.session.combat_state
        companion = CompanionState(id="companion_kael", name="Kael")
        f.session.companion = companion
        if producer == "player_damage":
            target = participant(state, f.ally)
        else:
            target = _player(companion.id, 1)
            target.type = "companion"
            state.participants.append(target)
            state.initiative_order.append(target.id)
            place_actors(state)
        if producer != "instant":
            target.hp_current, target.is_fallen, target.death_save_failures = 0, True, 2
        if producer == "save":
            call = game_tools(f.session, request_death_save)
            result = await save(call, target.id, 5)
            assert result["total_failures"] == 3 and "focus_renewals" not in result
            packets = await f.round(attack(f.ally, GOBLIN))
        else:
            packets = await f.round(attack(f.hero, GOBLIN), goblin_strike(OTHER, target.id), faces=(15, 15))
        previous = 5
        expected = [receipt(f.hero, GOBLIN, 3, previous)]
        saved = participant(await f.reload(), target.id)
        if producer in ("instant", "player_damage"):
            expected.append(receipt(f.hero, target.id, previous, 7))
            previous = 7
            assert saved.is_dead if producer == "instant" else saved.death_save_failures == 3
        else:
            assert (saved.death_save_failures, saved.death_save_successes, saved.is_dead) == (2, 3, False)
        assert renewals(packets) == expected
        assert await focus(world) == previous


async def test_death_save_and_renewal_roll_back_together(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="warden") as f:
        await setup_recipient(world, "warden")
        await f.round(goblin_strike(GOBLIN, f.ally))
        call = game_tools(f.session, request_death_save)
        for _ in range(2):
            await save(call, f.ally, 5)

        from _zhael_marshal_rally_fixtures import bonus, pending

        state = await f.reload()
        pending(state, f.ally, f.hero)
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())

        async def finish() -> dict:
            return await save(call, f.ally, 5)

        await rollback(world, f, finish, f.ally, "death_save_failures", 3)
        result = await finish()
        assert result["focus_renewals"] == [receipt(f.hero, f.ally, 3, 5)]
        assert result["rally_bonuses"] == [bonus(f.hero, f.ally)]
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        assert await focus(world) == 5


@pytest.mark.parametrize("burn", ["instant", "ordinary", "hollowed"])
async def test_inner_fire_only_renews_on_terminal_self_damage(world: SimpleNamespace, burn: str) -> None:
    async with fight(world, "mortaen", archetype="druid", goblin_hp=5) as f:
        await setup_recipient(world, "druid")
        hp = 9 if burn == "ordinary" else 1
        await configure(
            world,
            "mortaen",
            "warden",
            race="draethar",
            hp={"current": hp, "max": 20},
            maxhp_override=-17 if burn == "instant" else 0,
            focus={"current": 3, "max": 10},
            patron_gifts={"mortaen_death_ward": {"spent": True}},
        )
        await configure(world, "mortaen", "druid", index=1, focus={"current": 3, "max": 10})
        state = f.session.combat_state
        caster = participant(state, f.hero)
        projected = effective_hp(await row(world, 0))
        caster.hp_current, caster.hp_max = projected["current"], projected["max"]
        caster.conditions = _hollowed(2) if burn == "hollowed" else []
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        with patch("draethar_inner_fire.dice.roll", return_value=_d20(6)):
            result = await f.call("activate", id="draethar_inner_fire")
        assert result["fire_damage"] == 6
        caster = participant(await f.reload(), f.hero)
        if burn == "instant":
            assert caster.is_dead
            assert result.get("focus_renewals") == [receipt(f.ally, f.hero, 3, 5)]
            assert (await focus(world), await focus(world, 1)) == (3, 5)
        else:
            assert (caster.type, caster.hp_current) == (
                ("player", 3) if burn == "ordinary" else ("temporary_hollowed", 10)
            )
            assert "focus_renewals" not in result and await focus(world, 1) == 3
            packets = await f.round(attack(f.ally, GOBLIN))
            assert receipt(f.ally, GOBLIN, 3, 5) in renewals(packets)
            assert await focus(world, 1) == 5
