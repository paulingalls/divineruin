"""Lasting buffs through registered casts and reloaded combat and player state."""

import json
from unittest.mock import patch

import pytest
from _unbound_path_fixtures import world as world
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._spell_hostile_condition_helpers import add_player, attack, cast_spell, defend, play, receipt, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_spell_bless_lifecycle import context, ooc_player, swing
from acceptance.test_spell_new_conditions import equip, move
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant
from weapon_fixtures import DAGGER

import db
import db_mutations
import db_queries
from activate_tools import activate
from check_payloads import SaveCheck
from check_tools import check
from combat_death_save import request_death_save
from combat_end import end_combat
from party_state import PartyState

WARD = "divine_divine_ward"
BEACON = "divine_beacon_of_hope"
PROTECTION = "primal_protection_from_hollow"
HEAL = "divine_heal_wounds"


async def save_face(ctx, attribute, effect="resist"):
    payload = SaveCheck(kind="save", save_type=attribute, dc=13, effect_on_fail=effect)
    with patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(17)]):
        return json.loads(await check(ctx, payload))["roll"]


async def test_ward_halves_fire_until_its_casters_next_start(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "warrior")
    foe = await set_foe(ctx)
    other = await set_foe(ctx, foe_id="held")
    state = ctx.userdata.combat_state
    state.initiative_order = [caster, ally, foe.id, other.id]
    action = foe.action_pool[0]
    action.update(damage="12d1", damage_type="fire")
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await play(ctx, cast_spell(caster, "arcane_hold_person", other.id))
    before = participant(ctx.userdata.combat_state, ally).hp_current
    cast = cast_spell(caster, WARD, ally)
    strike = attack(foe.id, action["name"], ally)
    packets, state = await play(ctx, cast, move(ally, 0), strike, faces=[17, 1])
    assert receipt(packets, caster)["condition_targets"] == [ally]
    assert (swing(packets, foe.id)["roll"], swing(packets, foe.id)["damage"]) == (17, 6)
    assert participant(state, ally).hp_current == (await saved_player(ally))["hp"]["current"] == before - 6
    assert any(c["type"] == "paralyzed" for c in participant(state, other.id).conditions)
    packets, state = await play(ctx, strike, faces=[17, 1])
    assert (swing(packets, foe.id)["roll"], swing(packets, foe.id)["damage"]) == (17, 12)
    assert participant(state, ally).hp_current == (await saved_player(ally))["hp"]["current"] == before - 18
    assert any(c["type"] == "paralyzed" for c in participant(state, other.id).conditions)


async def test_beacon_three_recipients_have_scoped_saves_and_healing(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    selected = [caster, await add_player(ctx, "warrior"), await add_player(ctx, "warrior")]
    control = await add_player(ctx, "warrior")
    await set_foe(ctx)
    buff = cast_spell(caster, BEACON)
    buff.targets = selected
    packets, state = await play(ctx, buff, defend("foe"))
    assert receipt(packets, caster)["condition_targets"] == selected
    for pid in (*selected, control):
        save_ctx = context(pid)
        save_ctx.userdata.combat_state = state
        assert await save_face(save_ctx, "wisdom") == (17 if pid in selected else 5)
        assert await save_face(save_ctx, "dexterity") == 5


async def test_beacon_maximizes_exploration_heal_and_ends_on_replacement(dev_db_pool):
    caster = await ooc_player(BEACON, HEAL, "arcane_detect_magic")
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(jsonb_set(data,'{hp,current}','1'),'{attributes,wisdom}','16') "
        "WHERE player_id=$1",
        caster,
    )
    cast_ctx = context(caster)
    selected = [caster, await ooc_player(), await ooc_player()]
    control = await ooc_player()
    for pid in (*selected[1:], control):
        cast_ctx.userdata.party.members.append(PartyState.solo(pid).primary)
        await db_mutations.update_player_hp(pid, 1)
    packet = json.loads(await activate(cast_ctx, BEACON, target_ids=selected))
    assert packet["condition_targets"] == selected
    with patch("dice.roll", return_value=_damage_die(1)):
        result = json.loads(await activate(context(caster), HEAL))
    entry = result["healing_results"][0]
    assert (entry["rolled"], entry["modifier"], entry["healed"]) == (8, 3, 11)
    assert (await saved_player(caster))["hp"]["current"] == 12
    for pid in (*selected, control):
        assert await save_face(context(pid), "wisdom") == (17 if pid in selected else 5)
    await activate(cast_ctx, "arcane_detect_magic")
    for pid in selected:
        assert not (await saved_player(pid))["conditions"]
        assert await save_face(context(pid), "wisdom") == 5


async def test_protection_applies_to_documented_hollow_checks(dev_db_pool):
    caster = await ooc_player(PROTECTION, "arcane_detect_magic")
    control = await ooc_player()
    ctx = context(caster)
    await activate(ctx, PROTECTION)
    assert await save_face(context(caster), "constitution", "hollowed") == 17
    assert await save_face(context(control), "constitution", "hollowed") == 5
    assert await save_face(context(caster), "constitution") == 5
    await activate(ctx, "arcane_detect_magic")
    assert await save_face(context(caster), "constitution", "hollowed") == 5


async def test_beacon_at_death_saves_and_combat_healing(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally, control = [await add_player(ctx, "warrior") for _ in range(2)]
    foe = await set_foe(ctx)
    state = ctx.userdata.combat_state
    healer = await add_player(ctx, "cleric", (HEAL, "divine_mass_heal"))
    for pid in (ally, control):
        participant(state, pid).hp_current = 1
        await db_mutations.update_player_hp(pid, 1)
    participant(state, healer).attributes["wisdom"] = 16
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await play(ctx, cast_spell(caster, BEACON, ally), attack(foe.id, "Short Sword", ally), face=17)
    await play(ctx, attack(foe.id, "Short Sword", control), face=17)
    for pid, expected, counters in ((ally, 17, (1, 0)), (control, 5, (0, 1))):
        with patch("combat_resolution.dice_roll", side_effect=[_d20(5), _d20(17)]):
            result = json.loads(await request_death_save(ctx, pid))
        assert result["roll"] == expected
        fallen = participant(ctx.userdata.combat_state, pid)
        assert fallen.is_fallen
        assert (fallen.death_save_successes, fallen.death_save_failures) == counters

    with patch("dice.roll", return_value=_damage_die(1)):
        for pid, rolled in ((ally, 8), (control, 1)):
            packets, state = await play(ctx, cast_spell(healer, HEAL, pid), defend(foe.id))
            result = receipt(packets, healer)["healing_results"][0]
            assert (result["rolled"], result["modifier"], result["healed"]) == (rolled, 3, rolled + 3)
            revived = participant(state, pid)
            assert revived.hp_current == (await saved_player(pid))["hp"]["current"] == rolled + 3
            assert not revived.is_fallen
            assert (revived.death_save_successes, revived.death_save_failures) == (0, 0)

    with patch("dice.roll", return_value=_damage_die(2)):
        packets, state = await play(ctx, cast_spell(healer, "divine_mass_heal", None), defend(foe.id))
    outcomes = {entry["target_id"]: entry for entry in receipt(packets, healer)["healing_results"]}
    assert (outcomes[ally]["rolled"], outcomes[control]["rolled"]) == (16, 2)
    for pid in (ally, control):
        assert participant(state, pid).hp_current == (await saved_player(pid))["hp"]["current"]


async def test_protection_changes_mawling_attacks_and_hollow_saves_only(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally, control = [await add_player(ctx, "warrior") for _ in range(2)]
    maw = await set_foe(ctx, "hollow_mawling", foe_id="maw")
    bandit = await set_foe(ctx)
    state = ctx.userdata.combat_state
    for pid in (ally, control):
        actor = participant(state, pid)
        actor.ac = 16
        actor.attributes["constitution"] = 10
        await equip(ctx, pid, {**DAGGER, "id": "shortsword_basic"})
        await (await db.get_pool()).execute(
            "INSERT INTO player_inventory (player_id,item_id,data) VALUES ($1,'shortsword_basic',$2::jsonb)",
            pid,
            '{"equipped":true,"current_hits":10}',
        )
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await play(ctx, cast_spell(caster, PROTECTION, ally), defend(bandit.id), defend(maw.id))
    for source, name, target, expected, hit in (
        (maw, "Claw", ally, 5, False),
        (maw, "Claw", control, 17, True),
        (maw, "Claw", ally, 5, False),
        (bandit, "Short Sword", ally, 17, True),
    ):
        packets, _ = await play(ctx, attack(source.id, name, target), faces=[17, 5])
        landed = swing(packets, source.id)
        assert (landed["roll"], landed["hit"]) == (expected, hit)
    packets, _ = await play(ctx, attack(bandit.id, "Dirty Fighting", ally), faces=[5, 17])
    dirt = next(
        packet for packet in packets if packet["actor_id"] == bandit.id and packet.get("action") == "Dirty Fighting"
    )
    assert (dirt["save_roll"], dirt["save_success"]) == (5, False)

    for pid, expected in ((ally, True), (control, False)):
        dissolve = attack(maw.id, "Dissolution Maw", pid)
        dissolve.held_item_id = "shortsword_basic"
        faces = [17, 17, 5, 17] if pid == ally else [17, 5, 17]
        with patch("combat_item_rider.dice_roll", return_value=_damage_die(3)):
            packets, _ = await play(ctx, dissolve, faces=faces)
        result = swing(packets, maw.id)["durability_rider"]
        assert (result["save_total"], result["save_success"]) == ((17, True) if expected else (5, False))
        slot = await db_queries.get_inventory_item(pid, "shortsword_basic")
        assert slot is not None
        assert slot["current_hits"] == (10 if expected else 4)


@pytest.mark.parametrize("spell, kind", [(BEACON, "beacon_of_hope"), (PROTECTION, "protection_from_hollow")])
async def test_concentration_buffs_reconcile_and_release_only_their_caster(spell_fight, spell, kind):
    from acceptance._spell_hostile_condition_helpers import reload

    ctx = spell_fight
    first = ctx.userdata.player_id
    second = await add_player(ctx, "cleric", (spell, "arcane_detect_magic"))
    target = await add_player(ctx, "warrior")
    await set_foe(ctx)
    await play(ctx, cast_spell(first, spell, target), cast_spell(second, spell, target), defend("foe"))
    state = await reload(ctx)
    condition = participant(state, target).conditions[0]
    assert (condition["type"], condition["sustaining_caster_ids"]) == (kind, sorted([first, second]))
    await play(ctx, cast_spell(first, "arcane_detect_magic", None), defend("foe"))
    await end_combat(ctx, "fled")
    persisted = (await saved_player(target)).get("conditions", [])
    if spell == BEACON:
        assert persisted == []
        assert (await saved_player(second))["concentration"]["spell_id"] is None
    else:
        assert [(c["type"], c["sustaining_caster_ids"]) for c in persisted] == [(kind, [second])]
    with ctx.userdata._bind_authenticated_actor(second, 1, lambda *_: None):
        await activate(ctx, "arcane_detect_magic")
    assert not (await saved_player(target)).get("conditions")
    assert (await saved_player(first))["concentration"]["spell_id"] == "arcane_detect_magic"


@pytest.mark.parametrize("buffed", [True, False])
async def test_ward_reduces_fire_before_wild_shape_pool(spell_fight, buffed):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    shifter = await add_player(ctx, "druid", ("primal_wild_shape",))
    foe = await set_foe(ctx)
    state = ctx.userdata.combat_state
    action = foe.action_pool[0]
    action.update(damage="12d1", damage_type="fire")
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await db_mutations.update_player_hp(shifter, participant(state, shifter).hp_current)
    shape = cast_spell(shifter, "primal_wild_shape", None)
    shape.argument_type = "grey_wolf"
    await play(ctx, shape, defend(foe.id))
    hp_before = (await saved_player(shifter))["hp"]["current"]
    cast = cast_spell(caster, WARD, shifter) if buffed else defend(caster)
    packets, state = await play(ctx, cast, attack(foe.id, action["name"], shifter), face=17)
    landed = swing(packets, foe.id)
    assert (landed["damage"], landed["beast_hp_absorbed"]) == ((6, 6) if buffed else (12, 11))
    after = participant(state, shifter)
    if buffed:
        assert after.wild_shape is not None
        assert after.wild_shape["hp_current"] == 5
        assert "wild_shape_ended" not in landed
    else:
        assert after.wild_shape is None
        assert landed["wild_shape_ended"][0]["carryover_damage"] == 1
    assert after.hp_current == (await saved_player(shifter))["hp"]["current"] == hp_before - int(not buffed)


async def test_beacon_maximizes_verdant_healing_and_a_consumed_potion(dev_db_pool):
    from _item_heal_fixtures import ItemHealWalk
    from acceptance.seeds import seed_known_spells
    from test_heal_synergies import prepare
    from test_heal_synergies_place import VERDANT

    async with ItemHealWalk(dev_db_pool) as walk:
        caster = walk.player
        ally = await walk.add_player()
        await prepare(walk, caster, favor={"patron": "thyra", "level": 90, "max": 100})
        await seed_known_spells(walk.pool, caster, (BEACON, "primal_healing_touch"))
        await walk.command("activate", {"id": BEACON, "target_id": ally})
        with (
            patch("db_content_queries.get_location_terrain", return_value="forest"),
            patch("dice.roll", return_value=_damage_die(1)),
        ):
            cast = await walk.command("activate", {"id": "primal_healing_touch", "target_id": ally})
        heal = cast["healing_results"][0]
        assert (heal["rolled"], heal["modifier"], heal["healed"]) == (8, 3, 15)
        assert heal["synergy_components"] == [{"id": VERDANT, "bonus": 4}]
        assert (await walk.read(ally))["hp"]["current"] == heal["hp_current"]

        await walk.patch_row(ally, hp={"current": 3, "max": 20})
        await walk.put()
        with patch("dice.roll", return_value=_damage_die(4)):
            used = await walk.consume(target=ally)
        result = used["healing_results"][0]
        assert (result["rolled"], result["healed"]) == (10, 10)
        assert used["remaining_quantity"] == 1
        assert (await walk.read(ally))["hp"]["current"] == 13


async def test_beacon_ends_before_song_of_rest_rolls(world):
    from _zhael_fate_fixtures import game_tools
    from acceptance.seeds import seed_known_spells
    from test_orenthel_song_of_rest import song_party

    async with song_party(world, ("orenthel", "kaelen")) as rest:
        host, guest = world.ids
        await seed_known_spells(world.pool, host, (BEACON,))
        await world.pool.execute(
            "UPDATE players SET data=jsonb_set(data,'{focus,current}','12') WHERE player_id=$1", host
        )
        call = game_tools(world.ctx.userdata, activate)
        await call("activate", id=BEACON, target_id=guest)
        with patch("song_of_rest.roll", return_value=_damage_die(1)):
            packet = await rest("rest", rest_type="short", use_song_of_rest=True)
        heals = {entry["player_id"]: entry for entry in packet["song_of_rest"]["healing"]}
        for pid, expected in ((host, (1, 1, 5)), (guest, (1, 1, 5))):
            entry = heals[pid]
            assert (entry["roll"], entry["synergy_components"][0]["bonus"], entry["hp_after"]) == expected
            assert (await saved_player(pid))["hp"]["current"] == expected[2]


async def test_beacon_maximizes_hearthfire_for_its_recipient(world):
    from _aelora_hearthfire_fixtures import COMPANION, GIFT, hearth, point
    from _mortaen_threshold_fixtures import active, declare, drain
    from acceptance.seeds import seed_known_spells
    from test_patron_engine_valdris import checkpoint

    async with hearth(world) as call:
        caster, ally = world.ids
        await seed_known_spells(world.pool, caster, (BEACON,))
        active(world).spatial["positions"][ally] = point(10)
        await checkpoint(world)
        await declare(
            world,
            call,
            {"kind": "ability", "actor_id": caster, "action": BEACON, "targets": [ally], "argument_type": ""},
        )
        await drain(world, call)
        await call("activate", id=GIFT)
        await declare(world, call)
        with patch("dice.roll", return_value=_damage_die(1)):
            _, result = await drain(world, call)
        assert isinstance(result, dict)
        heals = {entry["target_id"]: entry for entry in result["hearthfire"]["heals"]}
        assert (heals[ally]["rolled"], heals[ally]["healed"]) == (6, 6)
        assert (heals[COMPANION]["rolled"], heals[COMPANION]["healed"]) == (1, 1)
        assert (await saved_player(ally))["hp"]["current"] == heals[ally]["hp_current"]


async def test_ward_reduces_fire_before_temporary_hp_and_clears_on_combat_end(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "warrior")
    foe = await set_foe(ctx)
    state = ctx.userdata.combat_state
    target = participant(state, ally)
    target.hp_current = 28
    target.temp_hp = 4
    await (await db.get_pool()).execute(
        "UPDATE players SET data=jsonb_set(data,'{temp_hp}','4') WHERE player_id=$1", ally
    )
    action = foe.action_pool[0]
    action.update(damage="12d1", damage_type="fire")
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    packets, state = await play(ctx, cast_spell(caster, WARD, ally), attack(foe.id, action["name"], ally), face=17)
    struck = swing(packets, foe.id)
    assert (struck["damage"], struck["temp_hp_absorbed"]) == (6, 4)
    player = await saved_player(ally)
    assert (player["hp"]["current"], player["temp_hp"]) == (26, 0)
    assert any(c["type"] == "divine_ward" for c in participant(state, ally).conditions)
    await end_combat(ctx, "fled")
    assert not any(c["type"] == "divine_ward" for c in (await saved_player(ally)).get("conditions", ()))
