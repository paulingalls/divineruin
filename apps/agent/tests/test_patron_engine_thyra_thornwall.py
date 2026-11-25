from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from _mortaen_threshold_fixtures import ENCOUNTER, drain, rolls
from _mortaen_threshold_fixtures import fight as catalog_fight
from _patron_engine_fixtures import configure
from _thyra_wrath_fixtures import checkpoint, fight, fighter, saved, snapshot
from _thyra_wrath_fixtures import refuse as refuse_wrath
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend
from acceptance._capstone_helpers import _d20
from combat.test_spell_damage_lands import prepare_spell
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant, spatial_record

import character_spells
import db_mutations
import event_types as E
from combat_structures import add_wall, collapse_wall
from dice import DiceResult

GIFT = "thyra_thornwall"
SEGMENT = {"start": {"x": 10, "y": -10, "z": 0}, "end": {"x": 10, "y": 10, "z": 0}}


async def placement(world):
    other = {"thyra_seasonal_attunement": {"spent": True}}
    async with fight(world, fighter("marauder"), favor=40, gifts=other) as call:
        actor = world.ids[0]
        state = world.ctx.userdata.combat_state
        spatial_record(state)["positions"]["marauder"]["x"] = 20
        await checkpoint(world)
        gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        assert (gift["tier"], gift["status"], gift["recharge"], gift["available"]) == (
            "Devoted",
            "active",
            "long_rest",
            True,
        )
        before = await row(world, 0)
        events_before = len(published_payloads(world.ctx.userdata.room))
        result = await call("activate", id=gift["id"], destination=SEGMENT)
        facts = result["wall"]
        assert facts["name"] == "Thornwall" and facts["segment"] == SEGMENT
        assert sorted([actor, "marauder"]) in facts["separates"]
        assert sorted(world.ids) not in facts["separates"]
        assert "Thornwall" in result["dm_cue"] and "Marauder" in result["dm_cue"]
        persisted = await saved(world)
        wall = participant(persisted, facts["id"])
        assert (wall.ac, wall.hp_current, wall.hp_max, wall.structure_kind) == (19, 20, 20, GIFT)
        assert wall.id not in persisted.initiative_order
        assert persisted.to_dict() == world.ctx.userdata.combat_state.to_dict()
        refreshed = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        assert gift["id"] in gift["activation_hint"]
        assert refreshed["spent"] and not refreshed["available"]
        assert "long rest" in refreshed["reason"]
        after = await row(world, 0)
        assert after["patron_gifts"] == {**other, GIFT: {"spent": True}}
        assert {stat: before[stat] for stat in ("hp", "focus", "stamina", "resonance")} == {
            stat: after[stat] for stat in ("hp", "focus", "stamina", "resonance")
        }
        query = await call("query_info", kind="combat")
        assert query["walls"] == [facts]
        assert all(name in " ".join(query["spoken"]) for name in ("Thornwall", "Rook", "Marauder"))
        events = published_payloads(world.ctx.userdata.room)[events_before:]
        assert any(e["type"] == E.COMBAT_UI_UPDATE and any(p["id"] == wall.id for p in e["combatants"]) for e in events)
        assert any(
            e["type"] == E.PATRON_ABILITIES_UPDATED and any(g["id"] == GIFT and g["spent"] for g in e["abilities"])
            for e in events
        )


SCENARIOS = {GIFT: ("thyra_thornwall:thornwall", placement, [()])}


def move(actor, x, y=0):
    return {
        "kind": "move",
        "actor_id": actor,
        "reshape": [],
        "movement_mode": "ground",
        "destination": {"x": x, "y": y, "z": 0},
    }


async def declare(world, call, *actions):
    state = world.ctx.userdata.combat_state
    actors = {action["actor_id"] for action in actions}
    return await call(
        "declare_phase",
        declarations=[
            *actions,
            *(
                defend(p.id)
                for p in state.participants
                if not p.is_structure and not p.is_fallen and p.id not in actors
            ),
        ],
    )


@pytest.mark.parametrize("melee,resistance,damage", [(False, False, 5), (True, True, 2)])
async def test_enemy_contact(world, melee, resistance, damage):
    claw = {"name": "Claw", "type": "melee", "damage": "1d6+2", "damage_type": "slashing"}
    enemy = fighter(
        "marauder",
        action_pool=[claw],
        damage_affinities={"resistant": ["piercing"]} if resistance else {},
    )
    async with fight(world, enemy, favor=40, gifts={}) as call:
        state = world.ctx.userdata.combat_state
        spatial_record(state)["positions"][enemy.id]["x"] = 20
        await checkpoint(world)
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        action = {**attack(enemy.id, world.ids[0]), "action": "Claw"} if melee else move(enemy.id, 0)
        declaration = await declare(world, call, action)
        assert declaration["spatial"]["walls"] == [wall]
        with patch("dice.roll", return_value=DiceResult("1d6", [5], [], 5)) as roll:
            packets, resolution = await drain(world, call)
        roll.assert_called_once_with("1d6")
        persisted = await saved(world)
        assert participant(persisted, enemy.id).hp_current == 50 - damage
        assert participant(persisted, world.ids[0]).hp_current == 50
        assert 10 < spatial_record(persisted)["positions"][enemy.id]["x"] < 20
        contact = next(packet for packet in packets if packet.get("thornwall_id") == wall["id"])
        assert isinstance(resolution, dict)
        assert resolution["spatial"]["walls"][0]["id"] == wall["id"]
        assert contact["thornwall_damage"]["damage"] == damage
        assert not contact.get("attack_resolved")


CLAW = {"name": "Claw", "type": "melee", "damage": "1d6", "damage_type": "slashing"}
BOW = {"name": "Bow", "type": "ranged", "reach": 60, "damage": "1d6", "damage_type": "piercing"}


@asynccontextmanager
async def battlefield(world, *foes, gifts=None, **options):
    async with fight(world, *foes, gifts=gifts or {}, **options) as call:
        state = world.ctx.userdata.combat_state
        for foe in foes:
            spatial_record(state)["positions"][foe.id]["x"] = 20
        await checkpoint(world)
        yield call


@pytest.mark.parametrize("route", ["player", "companion", "melee", "maneuver"])
async def test_ally_blocked(world, route):
    enemy = fighter("marauder")
    async with battlefield(world, enemy, favor=40) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        player = world.ids[0]
        action = {
            "player": move(player, 20),
            "companion": move("companion", 20),
            "melee": attack(player, enemy.id),
            "maneuver": {"kind": "maneuver", "actor_id": player, "target_id": enemy.id, "reshape": []},
        }[route]
        before = await snapshot(world)
        with pytest.raises(ToolError, match="Thornwall"):
            await declare(world, call, action)
        assert await snapshot(world) == before


async def test_route_around_endpoint(world):
    enemy = fighter("marauder")
    async with battlefield(world, enemy) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        await declare(world, call, move(world.ids[0], 12, 14))
        with patch("dice.roll") as roll:
            await drain(world, call)
        roll.assert_not_called()
        assert spatial_record(await saved(world))["positions"][world.ids[0]] == {"x": 12, "y": 14, "z": 0}


@pytest.mark.parametrize("mode", ["bow", "break"])
async def test_hostile_targeting(world, mode):
    enemy = fighter("marauder", action_pool=[BOW, CLAW])
    async with battlefield(world, enemy) as call:
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        state = world.ctx.userdata.combat_state
        stone = add_wall(state, "stone", "Stone Wall", {"x": -5, "y": -5, "z": 0}, {"x": -5, "y": 5, "z": 0})
        await checkpoint(world)
        if mode == "break":
            with pytest.raises(ToolError, match="cannot target Stone Wall"):
                await declare(world, call, {**attack(enemy.id, stone.id), "action": "Claw"})
        target = wall["id"] if mode == "break" else world.ids[0]
        await declare(world, call, {**attack(enemy.id, target), "action": "Claw" if mode == "break" else "Bow"})
        with rolls(19, damage=20 if mode == "break" else 5):
            packets, _ = await drain(world, call)
        state = await saved(world)
        barrier = participant(state, wall["id"])
        if mode == "bow":
            assert participant(state, target).hp_current < 50
            assert barrier.hp_current == 20
            return
        strike = next(p for p in packets if p.get("actor_id") == enemy.id)
        assert barrier.hp_current == 0, packets
        assert (strike["damage"], strike["target_ac"]) == (20, 19)
        assert barrier.hp_current == 0 and barrier.is_dead and barrier.is_fallen
        assert set(spatial_record(state)["structures"]) == {stone.id}
        await declare(world, call, move(enemy.id, 0))
        with patch("dice.roll") as roll:
            await drain(world, call)
        roll.assert_not_called()
        assert spatial_record(await saved(world))["positions"][enemy.id]["x"] == 0


async def test_nearest_stone_refuses_enemy_move_and_blocks_effects(world):
    enemy = fighter("marauder", action_pool=[BOW, CLAW])
    async with battlefield(world, enemy) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        player = world.ids[0]
        maneuver = {"kind": "maneuver", "actor_id": enemy.id, "target_id": player, "reshape": []}
        with pytest.raises(ToolError, match="Thornwall"):
            await declare(world, call, maneuver)
        state = world.ctx.userdata.combat_state
        outer = add_wall(state, "outer", "Outer Stone", {"x": 15, "y": -5, "z": 0}, {"x": 15, "y": 5, "z": 0})
        await checkpoint(world)
        with pytest.raises(ToolError, match="Outer Stone"):
            await declare(world, call, move(enemy.id, 0))
        with pytest.raises(ToolError, match="Outer Stone"):
            await declare(world, call, {**attack(enemy.id, player), "action": "Claw"})
        collapse_wall(state, outer)
        add_wall(state, "inner", "Inner Stone", {"x": 5, "y": -5, "z": 0}, {"x": 5, "y": 5, "z": 0})
        await checkpoint(world)
        with pytest.raises(ToolError, match="Inner Stone"):
            await declare(world, call, {**attack(enemy.id, world.ids[0]), "action": "Bow"})


@pytest.mark.parametrize("x,speed,damage", [(14, 0, 5), (25, 5, 0)])
async def test_contact_requires_reaching_wall(world, x, speed, damage):
    enemy = fighter("marauder", action_pool=[CLAW])
    async with battlefield(world, enemy) as call:
        state = world.ctx.userdata.combat_state
        spatial_record(state)["positions"][enemy.id]["x"] = x
        spatial_record(state)["speeds"][enemy.id] = speed
        await checkpoint(world)
        await call("activate", id=GIFT, destination=SEGMENT)
        player = world.ids[0]
        if x == 14:
            state = world.ctx.userdata.combat_state
            spatial_record(state)["positions"][player]["x"] = 9
            await checkpoint(world)
        await declare(world, call, {**attack(enemy.id, player), "action": "Claw"})
        with patch("dice.roll", return_value=DiceResult("1d6", [5], [], 5)) as roll:
            await drain(world, call)
        assert roll.call_count == bool(damage)
        persisted = await saved(world)
        assert participant(persisted, enemy.id).hp_current == 50 - damage
        assert spatial_record(persisted)["positions"][enemy.id]["x"] == x - speed
        assert participant(persisted, player).hp_current == 50


async def test_wrath_spares_thornwall(world):
    enemy = fighter("marauder")
    async with battlefield(world, enemy) as call:
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        with patch("dice.roll", return_value=DiceResult("3d8", [5, 5, 5], [], 15)):
            result = await call("activate", id="thyra_wildmothers_wrath")
        assert [target["id"] for target in result["targets"]] == [enemy.id]
        assert participant(await saved(world), wall["id"]).hp_current == 20


async def test_wrath_refuses_when_only_thornwall_remains(world):
    async with battlefield(world) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        await refuse_wrath(world, call, "no living unprotected foe")


@pytest.mark.parametrize("options", [{"favor": 39}, {"patron": "aelora"}, {"gifts": {GIFT: {"spent": True}}}])
async def test_ineligible_follower_is_atomic(world, options):
    async with battlefield(world, **options) as call:
        before = await snapshot(world)
        with pytest.raises(ToolError):
            await call("activate", id=GIFT, destination=SEGMENT)
        assert await snapshot(world) == before


async def test_composite_spends_contact_once_per_enemy_per_round(world):
    target = world.ids[0]
    enemy = fighter(
        "marauder", action_pool=[CLAW], multiattack_sequence={"name": "Double Claw", "attacks": ["Claw", "Claw"]}
    )
    async with battlefield(world, enemy) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        action = {
            "kind": "multiattack",
            "actor_id": enemy.id,
            "action": "Double Claw",
            "strikes": [{"action": "Claw", "target_id": target, "held_item_id": ""}] * 2,
        }
        with patch("dice.roll", return_value=DiceResult("1d6", [5], [], 5)) as roll:
            for round_number in (1, 2):
                await declare(world, call, action)
                first = await call("resolve_phase")
                world.ctx.userdata.combat_state = await saved(world)
                rest, _ = await drain(world, call)
                contacts = [p for p in first["packets"] + rest if p.get("thornwall_id")]
                assert len(contacts) == 2 and all(not p["attack_resolved"] for p in contacts)
                assert sum("thornwall_damage" in p for p in contacts) == 1
                assert roll.call_count == round_number
                assert participant(await saved(world), enemy.id).hp_current == 50 - 5 * round_number


async def test_lethal_contact_ends_encounter_with_wall_standing(world):
    enemy = fighter("marauder", hp=5)
    async with battlefield(world, enemy) as call:
        await call("activate", id=GIFT, destination=SEGMENT)
        combat_id = world.ctx.userdata.combat_state.combat_id
        await declare(world, call, move(enemy.id, 0))
        with patch("dice.roll", return_value=DiceResult("1d6", [5], [], 5)):
            _, handoff = await drain(world, call)
        assert handoff[1]["outcome"] == "victory"
        assert any("Marauder" in event and "5 automatic damage" in event for event in world.ctx.userdata.recent_events)
        assert await db_mutations.load_combat_state(combat_id, conn=world.pool) is None


async def test_encounter_end_discards_wall_keeps_spend(world):
    session = world.ctx.userdata
    async with catalog_fight(world, patron="thyra", favor=40, gifts={}) as call:
        old_id = session.combat_state.combat_id
        await call("activate", id=GIFT, destination=SEGMENT)
        await call("end_combat", outcome="fled")
        assert await db_mutations.load_combat_state(old_id, conn=world.pool) is None
        await call("enter_mode", mode="combat", encounter_id=ENCOUNTER)
        assert not (await call("query_info", kind="combat")).get("walls")
        gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
        assert gift["spent"]
        assert all(p.structure_kind != GIFT for p in session.combat_state.participants)


async def test_placement_requires_combat_geometry(world):
    async with battlefield(world) as call:
        session = world.ctx.userdata
        state = session.combat_state
        state.spatial = None
        await checkpoint(world)
        before = await snapshot(world)
        with pytest.raises(ToolError, match="no committed spatial placement"):
            await call("activate", id=GIFT, destination=SEGMENT)
        assert await snapshot(world) == before
        session.combat_state = None
        try:
            with pytest.raises(ToolError, match="only be used in combat"):
                await call("activate", id=GIFT, destination=SEGMENT)
            assert GIFT not in (await row(world, 0))["patron_gifts"]
        finally:
            session.combat_state = state


async def test_placement_at_both_range_limits(world):
    async with battlefield(world, favor=40) as call:
        segment = {"start": {"x": 30, "y": -10, "z": 0}, "end": {"x": 30, "y": 20, "z": 0}}
        result = await call("activate", id=GIFT, destination=segment)
        assert result["wall"]["segment"] == segment


@pytest.mark.parametrize(
    "spell,archetype",
    [
        ("arcane_bolt", "mage"),
        ("arcane_fireball", "mage"),
        ("arcane_chain_lightning", "mage"),
        ("divine_heal_wounds", "cleric"),
    ],
)
async def test_spell_delivery_across_thornwall(world, spell, archetype):
    enemy = fighter("marauder")
    near = fighter("nearby")
    async with battlefield(world, enemy, near, archetype=archetype) as call:
        caster, ally = world.ids
        state = world.ctx.userdata.combat_state
        spatial_record(state)["positions"][near.id]["x"] = 5
        spatial_record(state)["positions"][ally]["x"] = 25
        participant(state, ally).hp_current = 3
        await world.pool.execute("UPDATE players SET data=jsonb_set(data,'{hp,current}','3') WHERE player_id=$1", ally)
        if spell == "arcane_chain_lightning":
            participant(state, caster).level = 15
            await world.pool.execute(
                "UPDATE players SET data=jsonb_set(data,'{level}','15') WHERE player_id=$1", caster
            )
        await checkpoint(world)
        wall = (await call("activate", id=GIFT, destination=SEGMENT))["wall"]
        await prepare_spell(world.ctx, spell)
        await character_spells.record_learned(caster, spell, "discovery")
        target = ally if archetype == "cleric" else enemy.id
        await declare(
            world,
            call,
            {
                "kind": "ability",
                "actor_id": caster,
                "action": spell,
                "targets": [target, near.id] if spell == "arcane_chain_lightning" else [target],
                "argument_type": "",
                "reshape": [],
            },
        )
        with rolls(*([20] if spell == "arcane_bolt" else [1] * 16), damage=4):
            await drain(world, call)
        result = await saved(world)
        if archetype == "cleric":
            assert participant(result, ally).hp_current > 3
        else:
            assert participant(result, enemy.id).hp_current < 50
        wall_hp = participant(result, wall["id"]).hp_current
        if spell == "arcane_fireball":
            assert wall_hp < 20 and participant(result, near.id).hp_current < 50
        else:
            assert wall_hp == 20
            if spell == "arcane_chain_lightning":
                assert participant(result, near.id).hp_current < 50


async def test_wall_raised_after_declaration_stops_queued_ally_move(world):
    enemy = fighter("marauder")
    async with battlefield(world, enemy) as call:
        player = world.ids[0]
        await declare(world, call, move(player, 20))
        await call("activate", id=GIFT, destination=SEGMENT)
        with patch("dice.roll") as roll:
            packets, _ = await drain(world, call)
        roll.assert_not_called()
        assert any(p.get("resolved") is False and "Thornwall" in p.get("reason", "") for p in packets)
        assert spatial_record(await saved(world))["positions"][player]["x"] == 0


@pytest.mark.parametrize("melee", [False, True])
async def test_contact_survives_fate_pause_without_reroll_or_reposition(world, melee):
    knight = fighter(
        "knight",
        hp=5,
        action_pool=[CLAW],
        unholy_fortitude={"save": "CON", "dc": 10, "increment": 5, "narration_cue": "It rises."},
    )
    async with battlefield(world, knight) as call:
        await configure(world, "zhael", "warrior", index=1)
        await call("activate", id=GIFT, destination=SEGMENT)
        player, guest = world.ids
        action = {**attack(knight.id, player), "action": "Claw"} if melee else move(knight.id, 0)
        await declare(world, call, action)
        await call("resolve_phase")
        session = world.ctx.userdata
        with (
            patch("dice.roll", return_value=DiceResult("1d6", [5], [], 5)) as piercing,
            patch("check_resolution.dice_roll", return_value=_d20(18)) as fortitude,
        ):
            pending = await call("resolve_phase")
            offer = pending["fate_offer"]
            assert offer["roller_id"] == knight.id and offer["roll_kind"] == "save"
            paused = await saved(world)
            original = spatial_record(paused)["positions"][knight.id]
            assert 10 < original["x"] < 20 and participant(paused, knight.id).hp_current == 5
            session.combat_state = paused
            lifecycle = session.multiplayer_owner.lifecycle
            generation = await lifecycle.authorize(guest)
            assert generation
            with session._bind_authenticated_actor(guest, generation, lifecycle.require_authorized):
                resumed = await call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
        piercing.assert_called_once_with("1d6")
        fortitude.assert_called_once()
        contact = next(p for p in resumed["packets"] if p.get("thornwall_id"))
        assert contact["moved_ft"] > 0 and contact["destination"] == original
        assert contact["thornwall_damage"]["unholy_fortitude"]["success"]
        assert participant(await saved(world), knight.id).hp_current == 1


async def test_enemy_cone_reaches_players_across_thornwall(world):
    async with fight(world, encounter="hollow_veilrender_boss", gifts={}) as call:
        state = world.ctx.userdata.combat_state
        player = world.ids[0]
        enemy = next(p for p in state.participants if p.creature_id == "hollow_veilrender")
        spatial_record(state)["positions"][enemy.id] = {"x": 20, "y": 0, "z": 0}
        spatial_record(state)["positions"][player] = {"x": 0, "y": 0, "z": 0}
        await checkpoint(world)
        await call("activate", id=GIFT, destination=SEGMENT)
        await declare(world, call, {**attack(enemy.id, player), "action": "Corruption Wave"})
        with rolls(*([1] * 16), damage=4):
            packets, _ = await drain(world, call)
        wave = next(p for p in packets if p["actor_id"] == enemy.id and "targets" in p)
        assert any(target["target_id"] == player and target["damage"] > 0 for target in wave["targets"])
        assert participant(await saved(world), player).hp_current < 50
