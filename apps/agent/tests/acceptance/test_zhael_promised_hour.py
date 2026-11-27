"""Promised Hour saves through registered combat tools."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_marshal_rally_fixtures import pending, save_action
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._promised_hour_fixtures import manual_save, oath_record, promised_fight, select_oath, wrap
from acceptance.test_paladin_oath_swear import timed
from acceptance.test_valdris_oath_breach import dev_db_pool as dev_db_pool
from test_encounter_facts_damage import GOBLIN, dice, goblin_strike
from test_zhael_fate_sprint_saves import _keep, _reloaded, _reroll
from voice_condition_fixtures import participant

from conditions import apply_condition
from db_mutations_concentration import update_player_concentration


async def promised_hour(world) -> None:
    async with promised_fight(world) as f:
        before = await manual_save(f)
        assert (before["total"], before["outcome"]) == (9, "failure")
        oath = await select_oath(f)
        await f.round(faces=())
        await f.reload()
        save = await manual_save(f)
        assert (save["total"], save["outcome"]) == (10, "success")
        assert save["oath_timed"]["oath_id"] == oath["oath_id"]
        assert save["oath_timed"]["name"] == "Promised Hour"
        assert (save["combat_id"], save["round_number"]) == (f.combat_id, 3)


SCENARIOS = {"zhael_promised_hour": ("oath_timed:prepare_save", promised_hour, [()])}


@pytest.mark.parametrize("kind", ["damage_save", "concentration"])
async def test_automatic_effect_save(world, kind) -> None:
    async with promised_fight(world, ally_hp=20) as f:
        oath = await select_oath(f)
        await f.round(faces=())
        if kind == "concentration":
            f.session.member_state(f.hero).concentration.spell_id = "divine_bless"
            await update_player_concentration(f.hero, "divine_bless")
            packets = await f.round(goblin_strike(GOBLIN, f.hero), faces=(19, 9))
            receipt = next(packet["concentration_save"] for packet in packets if "concentration_save" in packet)
            assert (receipt["total"], receipt["success"]) == (10, True)
            assert f.session.member_state(f.hero).concentration.spell_id == "divine_bless"
        else:
            with patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
                packets = await f.round(save_action(f, f.hero), faces=(10,))
            receipt = next(packet for packet in packets if packet.get("actor_id") == GOBLIN)
            assert (receipt["save_total"], receipt["save_success"], receipt["damage"]) == (11, True, 2)
            assert participant(await f.reload(), f.hero).hp_current == 98
        assert receipt["oath_timed"]["oath_id"] == oath["oath_id"]
        assert receipt["round_number"] == 3


@pytest.mark.parametrize("held", [False, True])
async def test_final_round_clearing_save(world, held: bool) -> None:
    async with promised_fight(world) as f:
        oath = await select_oath(f, objective="keep_ally_standing", target=f.ally)
        await f.round(faces=())
        state = f.session.combat_state
        hero = participant(state, f.hero)
        hero.conditions = apply_condition([], "frightened", source=GOBLIN, duration=3)
        if held:
            hero.conditions = apply_condition(hero.conditions, "paralyzed", source=GOBLIN, duration=3)
            await configure(world, "zhael", "paladin", patron_gifts={})
        await f.declare()
        await f.call("resolve_phase")
        result = await wrap(f, 9)
        if held:
            assert result["fate_offer"]["offer_id"]
            assert (await oath_record(f))["status"] == "active"
            fresh, call = await _reloaded(f.session, f.combat_id, f.hero)
            await configure(
                world,
                "zhael",
                "paladin",
                patron_gifts={"zhael_fates_thread": {"spent": True}, "zhael_lucky": {"spent": True}},
            )
            with dice(9):
                result = await call("resolve_phase")
            assert fresh.combat_state.round_number == 4
        saves = result["oath_saves"]
        assert len(saves) == (2 if held else 1)
        for save in saves:
            assert (save["round_number"], save["total"], save["success"]) == (3, 10, True)
            assert save["oath_timed"]["oath_id"] == oath["oath_id"]
        [change] = result["oath_changes"]
        assert (change["new_status"], change["round_number"]) == ("fulfilled", 3)
        assert not participant(await f.reload(), f.hero).conditions


async def test_death_save_stacks_with_marshal(world) -> None:
    async with promised_fight(world) as f:
        await configure(world, "mortaen", "marshal", index=1)
        state = f.session.combat_state
        participant(state, f.ally).archetype_id = "marshal"
        await select_oath(f)
        await f.round(faces=())
        state = f.session.combat_state
        participant(state, f.hero).hp_current = 4
        boss = participant(state, GOBLIN)
        boss.legendary = {"points": 1, "actions": [{"id": "Scimitar", "kind": "attack", "cost": 1}]}
        boss.legendary_actions = 1
        with dice(19):
            blow = await f.call(
                "consume_legendary_action", boss_id=GOBLIN, action_id="Scimitar", target_id=f.hero, reshape=[]
            )
        assert blow["round"] == 3
        assert participant(await f.reload(), f.hero).is_fallen
        with patch("combat_resolution.dice_roll", return_value=_d20(9)):
            save = await f.call("request_death_save", player_id=f.hero)
        assert (save["total"], save["total_successes"], save["synergy_bonus"]) == (11, 1, 1)
        assert (save["round_number"], save["oath_timed"]["modifier"]) == (3, 1)


@pytest.mark.parametrize("choice", ["keep", "reroll", "lucky"])
async def test_prepared_save_stacks_once(world, choice: str) -> None:
    async with promised_fight(world) as f:
        oath = await select_oath(f)
        await f.round(faces=())
        gifts = {"zhael_fates_thread": {"spent": choice == "lucky"}, "zhael_lucky": {"spent": choice != "lucky"}}
        await configure(world, "zhael", "paladin", patron_gifts=gifts)
        pending(f.session.combat_state, f.hero, f.ally)
        offer = (await manual_save(f, 1 if choice == "lucky" else 8))["fate_offer"]
        if choice == "keep":
            save = await _keep(f.call, offer)
            face = 8
        elif choice == "reroll":
            with dice(9):
                save = await _reroll(f.call, offer)
            face = 9
        else:
            save = await f.call("activate", id="zhael_lucky", offer_id=offer["offer_id"])
            face = 20
        assert (save["roll"], save["total"], save["modifier"]) == (face, face + 2, 2)
        assert save["oath_timed"]["oath_id"] == oath["oath_id"]
        assert not f.session.combat_state.encounter_facts["rally_pending"]


async def test_pending_save_settles_before_registration(world) -> None:
    async with promised_fight(world) as f:
        offer = (await f.call("query_info", kind="combat"))["oath_choice"]
        await configure(world, "zhael", "paladin", patron_gifts={})
        assert (await manual_save(f))["fate_offer"]["offer_id"]
        selection = await f.call("select", **timed(offer, target=GOBLIN))
        assert selection["settled_fate"]["total"] == 9
        assert selection["oath_id"] == (await oath_record(f))["id"]
        await configure(
            world,
            "zhael",
            "paladin",
            patron_gifts={"zhael_fates_thread": {"spent": True}, "zhael_lucky": {"spent": True}},
        )
        assert (await manual_save(f))["total"] == 10
