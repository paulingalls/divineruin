"""Rally consumption at registered save boundaries."""

from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from _zhael_marshal_rally_fixtures import CLAUSE, bonus, pending, save_action
from acceptance._capstone_helpers import _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from test_encounter_facts_damage import GOBLIN, dice, fight, goblin_strike
from test_encounter_facts_heal import save as death_roll
from test_zhael_fate_sprint_saves import _settle
from voice_condition_fixtures import participant

import db_mutations
from check_tools import check
from combat_death_save import request_death_save
from combat_end import end_combat
from conditions import apply_condition

MANUAL = {"kind": "save", "save_type": "wisdom", "dc": 11, "effect_on_fail": "shaken"}


async def persist(f) -> None:
    await db_mutations.save_combat_state(f.combat_id, f.session.combat_state.to_dict())
    await f.reload()


async def test_manual_save_and_expiry(world) -> None:
    async with fight(world, "thyra", ally_hp=20) as f:
        pending(f.session.combat_state, f.hero, f.ally)
        await persist(f)
        call = game_tools(f.session, check, end_combat)
        with dice(10):
            receipt = await call("check", roll=MANUAL)
        assert (receipt["total"], receipt["outcome"], receipt["rally_bonuses"]) == (
            11,
            "success",
            [bonus(f.ally, f.hero)],
        )
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        pending(f.session.combat_state, f.hero, f.ally)
        await persist(f)
        await call("end_combat", outcome="fled")
        assert await db_mutations.load_combat_state(f.combat_id) is None
        with dice(10):
            receipt = await call("check", roll=MANUAL)
        assert (receipt["total"], receipt.get("rally_bonuses")) == (10, None)


async def test_death_save_composes_rally_and_hold_the_crossing(world) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        pending(f.session.combat_state, f.ally, "zhael-marshal")
        await f.round(goblin_strike(GOBLIN, f.ally))
        assert participant(f.session.combat_state, f.ally).hp_current == 0
        call = game_tools(f.session, request_death_save)
        rolled = await death_roll(call, f.ally, 8)
        assert (rolled["success"], rolled["bonus"], rolled["synergy_clause_id"]) == (
            True,
            2,
            "mortaen_hold_the_crossing",
        )
        assert rolled["rally_bonuses"] == [bonus("zhael-marshal", f.ally)]
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        rolled = await death_roll(call, f.ally, 8)
        assert (rolled["success"], rolled["bonus"], rolled.get("rally_bonuses")) == (False, 1, None)


@pytest.mark.parametrize("reload", [False, True])
async def test_held_save_keeps_rally_once(world, reload) -> None:
    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        await configure(world, "zhael", "marshal", patron_gifts={"zhael_lucky": {"spent": True}})
        pending(f.session.combat_state, f.ally, f.hero)
        await persist(f)
        await f.declare(save_action(f, f.ally))
        with dice(10, 13), patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
            result = await f.call("resolve_phase")
            if "fate_offer" not in result:
                result = await f.call("resolve_phase")
            offer = result["fate_offer"]
            assert offer["roll_kind"] == "save" and offer["total"] == 11
            held = await db_mutations.load_combat_state(f.combat_id)
            assert held is not None
            assert held.encounter_facts["rally_pending"] == {f.hero: f.ally}
            stored = held.held_actions[0]["roll_steps"]["save"]
            assert (stored["d20"]["modifier"], stored["rally_sources"]) == (1, [f.hero])
            result, final = await _settle(world, f.session, held, f.call, offer, reload)
        assert final.encounter_facts["rally_pending"] == {}
        [receipt] = [p for p in result["packets"] if p.get("actor_id") == GOBLIN and "save_total" in p]
        assert (receipt["save_total"], receipt["rally_bonuses"]) == (11 if reload else 14, [bonus(f.hero, f.ally)])
        assert (await f.reload()).encounter_facts["once_spent"][CLAUSE] == [f.hero]


async def test_wrap_clearing_save_spends_rally(world) -> None:
    async with fight(world, "thyra", ally_hp=20) as f:
        ally = participant(f.session.combat_state, f.ally)
        ally.conditions = apply_condition([], "frightened", source=GOBLIN, duration=3)
        pending(f.session.combat_state, f.ally, f.hero)
        await persist(f)
        await f.declare()
        await f.call("resolve_phase")
        with dice(9):
            result = await f.call("resolve_phase")
        [receipt] = result["rally_saves"]
        assert (receipt["total"], receipt["success"], receipt["rally_bonuses"]) == (10, True, [bonus(f.hero, f.ally)])
        assert (await f.reload()).encounter_facts["rally_pending"] == {}
        assert not participant(f.session.combat_state, f.ally).conditions


@pytest.mark.parametrize("mode", ["condition", "combined", "critical", "concentration", "corrosion"])
async def test_enemy_save_owners_spend_rally(world, mode) -> None:
    from acceptance.test_inventory_taint import seed_stack

    from creature_combat_loader import load_creature_enemy
    from db_mutations_concentration import update_player_concentration

    async with fight(world, "thyra", ally_hp=20) as f:
        state = f.session.combat_state
        pending(state, f.ally, f.hero)
        enemy = participant(state, GOBLIN)
        action = goblin_strike(GOBLIN, f.ally)
        faces = (19, 9)
        receipt_name = None
        field = "save_total"
        expected = 10
        item = "shortsword_basic"
        if mode in ("condition", "combined"):
            enemy.action_pool = [
                {
                    **(enemy.action_pool[0] if mode == "combined" else {}),
                    "name": "Poisoning Strike",
                    "save": "CON",
                    "dc": 10,
                    "applies_condition": "poisoned",
                }
            ]
            action["action"] = "Poisoning Strike"
            if mode == "condition":
                action = {
                    "kind": "ability",
                    "actor_id": GOBLIN,
                    "action": "Poisoning Strike",
                    "targets": [f.ally],
                    "argument_type": "",
                    "reshape": [],
                }
                faces = (9,)
        elif mode == "critical":
            knight = await load_creature_enemy(
                "hollow_knight", encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard"
            )
            [strike] = [a for a in knight["action_pool"] if "critical_save" in a]
            enemy.action_pool = [strike]
            action["action"] = strike["name"]
            faces, expected = (20, 13), 14
            receipt_name, field = "critical_save", "total"
        elif mode == "concentration":
            f.session.member_state(f.ally).concentration.spell_id = "divine_bless"
            await update_player_concentration(f.ally, "divine_bless")
            receipt_name, field = "concentration_save", "total"
        else:
            maw = await load_creature_enemy(
                "hollow_mawling", encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard"
            )
            [strike] = [a for a in maw["action_pool"] if "durability_rider" in a]
            enemy.action_pool = [strike]
            action.update(action=strike["name"], held_item_id=item)
            expected = strike["durability_rider"]["dc"]
            faces = (19, expected - 1)
            receipt_name = "durability_rider"
            await seed_stack(world.pool, f.ally, item, 1, False, equipped=True, current_hits=10)
        await persist(f)
        try:
            packets = await f.round(action, faces=faces)
            packet = next(p for p in packets if p.get("actor_id") == GOBLIN)
            receipt = packet if receipt_name is None else packet[receipt_name]
            assert (receipt[field], receipt["rally_bonuses"]) == (expected, [bonus(f.hero, f.ally)])
            assert receipt.get("save_success", receipt.get("success")) is True
            assert (await f.reload()).encounter_facts["rally_pending"] == {}
        finally:
            if mode == "corrosion":
                await world.pool.execute("DELETE FROM player_inventory WHERE player_id=$1 AND item_id=$2", f.ally, item)


@pytest.mark.parametrize("mode", ["choir_area", "melody", "aura", "shield", "field", "area_spell"])
async def test_catalog_save_owners_spend_rally(world, mode) -> None:
    from acceptance.seeds import seed_known_spells
    from creature_combat_helpers import participant as from_creature
    from sample_fixtures import published_payloads

    import choir_encounter
    from creature_combat_loader import load_creature_enemy

    async with fight(world, "none", archetype="mage", ally_hp=20) as f:
        state = f.session.combat_state
        state.terrain = "city"
        target = f.hero if mode in ("aura", "shield") else f.ally
        source = f.ally if target == f.hero else f.hero
        pending(state, target, source)
        enemy = participant(state, GOBLIN)
        if mode != "area_spell":
            creature_id = "hollow_veilrender" if mode == "field" else "hollow_choir"
            row = await load_creature_enemy(creature_id, encounter_id=f.combat_id, enemy_id=GOBLIN, role="standard")
            state.participants[state.participants.index(enemy)] = enemy = from_creature(row)
        assert state.spatial is not None
        coords = {f.hero: (0, 0), GOBLIN: (50, 0), f.ally: (55, 0), "goblin_two": (190, 0)}
        for pid, (x, y) in coords.items():
            state.spatial["positions"][pid] = {"x": x, "y": y, "z": 0}
        if mode in ("choir_area", "melody"):
            name = "Memory Scream" if mode == "choir_area" else "Stolen Melody"
            spec = next(a for a in enemy.action_pool if a["name"] == name)
            strikes = (
                {**goblin_strike(GOBLIN, target), "action": name}
                if mode == "choir_area"
                else {
                    "kind": "ability",
                    "actor_id": GOBLIN,
                    "action": name,
                    "targets": [target],
                    "argument_type": "",
                    "reshape": [],
                },
            )
            faces = (20, spec["dc"] - 1) if mode == "choir_area" else (spec["dc"] - 1,)
        elif mode == "aura":
            choir_encounter.initialize(state)
            strikes, faces = (), (14, 20, 20)
        elif mode == "field":
            assert enemy.corruption_field is not None
            strikes, faces = (), (enemy.corruption_field["dc"] - 1,)
            state.spatial["positions"][f.ally]["x"] = 51
            state.spatial["positions"][f.hero]["x"] = -100
        else:
            spell = "arcane_bolt" if mode == "shield" else "arcane_fireball"
            await seed_known_spells(world.pool, f.hero, (spell,))
            strikes = (
                {
                    "kind": "ability",
                    "actor_id": f.hero,
                    "action": spell,
                    "targets": [GOBLIN],
                    "argument_type": "",
                    "reshape": [],
                },
            )
            faces = (15, 19) if mode == "shield" else (20, 20)
        await persist(f)
        with (
            patch("dice.roll", return_value=_damage_die(4)),
            patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)),
        ):
            packets = await f.round(*strikes, faces=faces)
        if mode == "aura":
            receipt = next(
                e
                for e in published_payloads(f.session.room)
                if e.get("roll_type") == "choir_aura" and e["actor_id"] == target
            )
        elif mode == "field":
            receipt = next(e for p in packets for e in p.get("turn_start_effects", []) if e["actor_id"] == target)
        elif mode in ("choir_area", "melody"):
            receipt = next(
                p
                for p in packets
                if p.get("actor_id") == GOBLIN and p.get("rally_bonuses" if mode == "melody" else "targets")
            )
            if mode == "choir_area":
                receipt = next(p for p in receipt["targets"] if p["target_id"] == target)
        else:
            cast = next(p["cast"] for p in packets if "cast" in p)
            if mode == "shield":
                [receipt] = cast["harmonic_shield_saves"]
            else:
                receipt = next(p["save"] for p in cast["damage_results"] if p["target_id"] == target)
        assert receipt["rally_bonuses"] == [bonus(source, target)]
        assert receipt.get("save_success", receipt.get("success")) is True
        assert (await f.reload()).encounter_facts["rally_pending"] == {}


@pytest.fixture
async def still(dev_db_pool):
    harness = MawlingHarness()
    try:
        await harness.prepare((18,), companion=None, location="ashmark_still")
        yield harness
    finally:
        await harness.close()


@pytest.mark.parametrize("action", ["Serenity's Touch", "Final Stillness"])
async def test_still_save_owners_spend_rally(still, action) -> None:
    from acceptance.test_still_actions import reveal_and_wake
    from acceptance.test_still_anchors import declare, destroy, search_round, spell, strike

    from check_resolution import D20Roll

    state = await reveal_and_wake(still)
    assert state.still_encounter is not None
    owner = state.still_encounter["owner_id"]
    target = still.players[0]
    source = "zhael-marshal"
    if action == "Final Stillness":
        for anchor in state.still_encounter["anchor_ids"][:4]:
            if anchor not in state.still_encounter["revealed_ids"]:
                await search_round(still, {"action": "still_search_arcana"})
            await destroy(still, anchor)
        state = await still.reload()
    assert state.spatial is not None
    state.spatial["positions"][target] = {**state.spatial["positions"][owner], "x": 120}
    roller = participant(state, target)
    roller.attributes["wisdom"] = 10
    roller.saving_throw_proficiencies = []
    pending(state, target, source)
    await still.persist()
    await still.reload()
    payload = strike(target, action=action) if action == "Serenity's Touch" else spell(action)
    await declare(still, actor_id=owner, **payload)
    expected = 20 if action == "Serenity's Touch" else 22
    with (
        patch("dice.roll", return_value=_damage_die(5)),
        patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(expected - 1)),
    ):
        packets = await still.drain()
    packet = next(p for p in packets if p.get("action") == action)
    receipt = packet if action == "Serenity's Touch" else packet["targets"][0]
    assert (receipt["save_total"], receipt["save_success"], receipt["rally_bonuses"]) == (
        expected,
        True,
        [bonus(source, target)],
    )
    assert (await still.reload()).encounter_facts["rally_pending"] == {}


async def test_manual_fate_save_consumes_rally_and_blessed_together(world) -> None:
    from _unbound_path_fixtures import row
    from test_zhael_fate_sprint_saves import _reroll

    from activate_tools import activate

    async with fight(world, "zhael", ally_hp=20) as f:
        blessed = apply_condition([], "blessed", source="divine_bless")
        await configure(world, "zhael", "warrior", conditions=blessed, patron_gifts={"zhael_lucky": {"spent": True}})
        state = f.session.combat_state
        participant(state, f.hero).conditions = blessed
        pending(state, f.hero, f.ally)
        await persist(f)
        call = game_tools(f.session, check, activate)
        with dice(8, 9), patch("condition_bonus.dice_roll", return_value=_damage_die(1)):
            held = await call("check", roll=MANUAL)
            offer = held.get("fate_offer", held)
            assert (offer["die"], offer["total"]) == (8, 10)
            saved = await db_mutations.load_combat_state(f.combat_id)
            assert saved is not None and saved.encounter_facts["rally_pending"] == {f.ally: f.hero}
            result = await _reroll(call, offer)
        assert (result["total"], result["outcome"], result["rally_bonuses"]) == (11, "success", [bonus(f.ally, f.hero)])
        saved = await f.reload()
        assert saved.encounter_facts["rally_pending"] == {}
        assert participant(saved, f.hero).conditions == []
        assert (await row(world, 0))["conditions"] == []


async def test_completed_damage_save_cannot_rally_its_concentration_save(world) -> None:
    from test_zhael_fate_sprint_saves import _keep

    from db_mutations_concentration import update_player_concentration

    async with fight(world, "zhael", archetype="marshal", ally_hp=20) as f:
        await configure(world, "zhael", "marshal", patron_gifts={"zhael_lucky": {"spent": True}})
        f.session.member_state(f.ally).concentration.spell_id = "divine_bless"
        await update_player_concentration(f.ally, "divine_bless")
        pending(f.session.combat_state, f.ally, f.hero)
        await f.declare(save_action(f, f.ally))
        with dice(10, 9), patch("combat_enemy_action.dice_roll", return_value=_damage_die(4)):
            await f.call("resolve_phase")
            damage_save = (await f.call("resolve_phase"))["fate_offer"]
            concentration = (await _keep(f.call, damage_save))["fate_offer"]
            assert (damage_save["total"], concentration["total"]) == (11, 9)
            held = await db_mutations.load_combat_state(f.combat_id)
            assert held is not None and held.encounter_facts["rally_pending"] == {}
            selected = held.held_actions[0]["roll_steps"]["selected_save"]
            assert selected["rally_sources"] == [f.hero]
            result = await _keep(f.call, concentration)
        landed = next(p for p in result["packets"] if p.get("actor_id") == GOBLIN)
        assert landed["rally_bonuses"] == [bonus(f.hero, f.ally)]
        assert landed["concentration_broken"] == "divine_bless"
        assert "concentration_save" not in landed
