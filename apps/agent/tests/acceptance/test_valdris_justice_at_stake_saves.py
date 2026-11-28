"""Sourced saves through registered combat."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_marshal_rally_fixtures import ability, save_action
from acceptance._capstone_helpers import _damage_die
from acceptance.test_inventory_taint import seed_stack
from acceptance.test_valdris_oath_breach import dev_db_pool as dev_db_pool
from acceptance.test_valdris_oath_breach import registered, swear
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, OTHER, dice, fight, goblin_strike
from test_zhael_fate_sprint_saves import _keep, _reloaded, _reroll
from voice_condition_fixtures import participant

import db_mutations
from conditions import apply_condition
from creature_combat_loader import load_creature_enemy
from db_mutations_concentration import update_player_concentration


async def test_hostile_damage_save(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        packets = await f.round(save_action(f, f.hero), faces=(10,))
        receipt = next(p for p in packets if p.get("actor_id") == GOBLIN and "save_total" in p)
        assert receipt["save_total"] == 12
        assert receipt["oath_justice"]["oath_id"] == oath["oath_id"]
        assert receipt["oath_justice"]["source_id"] == GOBLIN
        [event] = [e for e in published_payloads(f.session.room) if e.get("oath_justice")]
        assert event["total"] == 12 and event["oath_justice"] == receipt["oath_justice"]


@pytest.mark.parametrize("resolution", ["condition", "combined", "critical", "concentration", "corrosion", "tick"])
async def test_automatic_save_uses_its_effect_owner(world, resolution) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        state = f.session.combat_state
        hero = participant(state, f.hero)
        goblin = participant(state, GOBLIN)
        strike = goblin_strike(GOBLIN, f.hero)
        field = "save_total"
        nested = None
        dc = 10
        faces = (19, 8)
        inventory_item = "shortsword_basic"

        if resolution in {"condition", "combined"}:
            goblin.action_pool = [
                {
                    **(goblin.action_pool[0] if resolution == "combined" else {}),
                    "name": "Poisoning Strike",
                    "save": "CON",
                    "dc": dc,
                    "applies_condition": "poisoned",
                }
            ]
            strike["action"] = "Poisoning Strike"
            if resolution == "condition":
                strike = ability(GOBLIN, strike["action"], f.hero)
                faces = (8,)
        elif resolution in {"critical", "corrosion"}:
            creature = "hollow_knight" if resolution == "critical" else "hollow_mawling"
            spec = await load_creature_enemy(creature, encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard")
            nested = "critical_save" if resolution == "critical" else "durability_rider"
            [action] = [a for a in spec["action_pool"] if nested in a]
            goblin.action_pool = [action]
            strike["action"] = action["name"]
            dc = action[nested]["dc"]
            faces = (20 if resolution == "critical" else 19, dc - 2)
            if resolution == "critical":
                field = "total"
            else:
                strike["held_item_id"] = inventory_item
                await seed_stack(world.pool, f.hero, inventory_item, 1, False, equipped=True, current_hits=10)
        elif resolution == "concentration":
            f.session.member_state(f.hero).concentration.spell_id = "divine_bless"
            await update_player_concentration(f.hero, "divine_bless")
            nested, field = "concentration_save", "total"
        else:
            hero.conditions = apply_condition(
                [], "frightened", source="a different narrative label", duration=3, originating_participant_id=GOBLIN
            )
            await f.declare()
            await f.call("resolve_phase")
            with dice(8):
                result = await f.call("resolve_phase")
            [receipt] = result["oath_saves"]
            assert {key: value for key, value in receipt.items() if key != "oath_justice"} == {
                "actor_id": f.hero,
                "condition": "frightened",
                "roll": 8,
                "total": 10,
                "dc": 10,
                "success": True,
                "combat_id": f.combat_id,
                "round_number": 2,
            }
            assert receipt["oath_justice"]["source_id"] == GOBLIN
            assert (receipt["oath_justice"]["oath_id"], receipt["oath_justice"]["modifier"]) == (oath["oath_id"], 2)
            assert "rally_saves" not in result
            assert not participant(await f.reload(), f.hero).conditions
            return

        packets = await f.round(strike, faces=faces)
        attack_packet = next(p for p in packets if p["actor_id"] == GOBLIN)
        receipt = attack_packet[nested] if nested else attack_packet
        assert receipt[field] == dc
        assert receipt.get("save_success", receipt.get("success")) is True
        assert receipt["oath_justice"]["oath_id"] == oath["oath_id"]
        assert receipt["oath_justice"]["source_id"] == GOBLIN
        hero = participant(await f.reload(), f.hero)
        if resolution in {"condition", "combined", "critical"}:
            assert not hero.conditions
        elif resolution == "concentration":
            assert {key: value for key, value in receipt.items() if key != "oath_justice"} == {
                "roll": 8,
                "total": 10,
                "dc": 10,
                "success": True,
                "combat_id": f.combat_id,
                "round_number": 2,
            }
            assert receipt["oath_justice"]["modifier"] == 2
            assert f.session.member_state(f.hero).concentration.spell_id == "divine_bless"
        else:
            assert receipt["applied"] is False


@pytest.mark.parametrize("choice", ["original", "reroll", "reload"])
async def test_held_hostile_save_freezes_origin_and_modifier(world, choice) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, f.hero, f.ally)
        try:
            await f.declare(save_action(f, f.hero))
            with dice(8, 10), patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
                await f.call("resolve_phase")
                offer = (await f.call("resolve_phase"))["fate_offer"]
                assert (offer["roll_kind"], offer["total"], offer["roller_id"]) == ("save", 10, f.hero)
                saved = await db_mutations.load_combat_state(f.combat_id)
                assert saved is not None
                stored = saved.held_actions[0]["roll_steps"]["save"]
                assert stored["originating_participant_id"] == GOBLIN
                assert stored["d20"]["modifier"] == 2
                if choice == "reload":
                    session, call = await _reloaded(f.session, f.combat_id, f.hero)
                    result = await call("resolve_phase")
                else:
                    session = f.session
                    with session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
                        result = await (_reroll(f.call, offer) if choice == "reroll" else _keep(f.call, offer))
            receipt = next(p for p in result["packets"] if p.get("actor_id") == GOBLIN and "save_total" in p)
            assert receipt["oath_justice"]["oath_id"] == oath["oath_id"]
            assert receipt["oath_justice"]["source_id"] == GOBLIN
            assert receipt["save_total"] == (12 if choice == "reroll" else 10)
            assert receipt["save_success"] is (choice == "reroll")
            assert participant(session.combat_state, f.hero).hp_current == (98 if choice == "reroll" else 96)
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("wrong_id", [False, True])
async def test_tick_validates_its_explicit_source(world, wrong_id) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        if not wrong_id:
            await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        participant(f.session.combat_state, f.hero).conditions = apply_condition(
            [],
            "frightened",
            source=GOBLIN,
            duration=3,
            originating_participant_id="unknown_runtime_id" if wrong_id else OTHER,
        )
        await f.declare()
        await f.call("resolve_phase")
        with dice(8):
            if wrong_id:
                with pytest.raises(ToolError, match="Unknown save source: unknown_runtime_id"):
                    await f.call("resolve_phase")
                return
            response = await f.call("resolve_phase")
        [receipt] = response["oath_saves"]
        assert receipt["total"] == 8
        assert receipt["oath_justice"]["reason"] == "no_wrongdoer"
        assert receipt["oath_justice"]["source_id"] == OTHER
        assert participant(await f.reload(), f.hero).conditions


async def test_reloading_held_concentration_keeps_both_save_receipts(world) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        oath = await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        f.session.member_state(f.hero).concentration.spell_id = "divine_bless"
        await update_player_concentration(f.hero, "divine_bless")
        await configure(world, "zhael", "warrior", index=1, patron_gifts={"zhael_lucky": {"spent": True}})
        lifecycle = _live_party(f.session, f.hero, f.ally)
        try:
            await f.declare(save_action(f, f.hero))
            with dice(10, 8), patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
                await f.call("resolve_phase")
                initial = (await f.call("resolve_phase"))["fate_offer"]
                assert initial["total"] == 12
                with f.session._bind_authenticated_actor(f.ally, 1, lambda *_: None):
                    next_offer = (await _keep(f.call, initial))["fate_offer"]
                assert next_offer["total"] == 10
            session, call = await _reloaded(f.session, f.combat_id, f.hero)
            session.member_state(f.hero).concentration.spell_id = "divine_bless"
            with dice():
                result = await call("resolve_phase")
            packet = next(p for p in result["packets"] if p.get("actor_id") == GOBLIN and "save_total" in p)
            assert packet["save_total"] == 12
            concentration = packet["concentration_save"]
            assert (concentration["roll"], concentration["total"], concentration["success"]) == (8, 10, True)
            for receipt in (packet, concentration):
                assert receipt["oath_justice"] == {
                    "oath_id": oath["oath_id"],
                    "context": "save",
                    "source_id": GOBLIN,
                    "modifier": 2,
                    "reason": "aggression",
                }
            assert session.member_state(f.hero).concentration.spell_id == "divine_bless"
            assert participant(session.combat_state, f.hero).hp_current == 98
        finally:
            await lifecycle.aclose()


@pytest.mark.parametrize("face,damage,constitution,success", [(1, 4, 28, False), (20, 60, 10, True)])
async def test_concentration_uses_natural_save_verdict(world, face, damage, constitution, success) -> None:
    async with fight(world, "valdris", archetype="paladin", ally_hp=20) as f:
        registered(f)
        await swear(f.session)
        await f.round(goblin_strike(GOBLIN, f.hero), faces=(1,))
        await configure(world, "valdris", "paladin", attributes={"constitution": constitution})
        f.session.member_state(f.hero).concentration.spell_id = "divine_bless"
        await update_player_concentration(f.hero, "divine_bless")
        with patch("combat_enemy_action.dice_roll", return_value=_damage_die(damage)):
            packets = await f.round(save_action(f, f.hero), faces=(1, face))
        packet = next(p for p in packets if p.get("actor_id") == GOBLIN and "save_total" in p)
        concentration = packet["concentration_save"]
        assert concentration["roll"] == face
        assert (concentration["total"] >= concentration["dc"]) is not success
        assert concentration["success"] is success
        assert (f.session.member_state(f.hero).concentration.spell_id == "divine_bless") is success
