from contextlib import asynccontextmanager, contextmanager
from unittest.mock import patch

from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from sample_fixtures import published_payloads
from test_aelora_gift import _live_party
from test_patron_engine_valdris import checkpoint, reload_state
from voice_condition_fixtures import participant

import character_spells
import db_mutations
import still_encounter
from activate_tools import activate
from combat_end import end_combat
from combat_init_validation import validate_enemy_action_shapes
from combat_turn import declare_phase, resolve_phase
from encounter_actions import validate_encounter_actions
from mode_tools import enter_mode
from query_tools import query_info
from recipe_tools import learn

GIFT = "mortaen_threshold_walk"
FOE = "mawling_1"
ENCOUNTER = "ruins_mawling_pair"
OTHER_GIFTS = {"mortaen_speak_with_dead": {"spent": True}}
SWORD = {"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}


@asynccontextmanager
async def fight(
    world,
    *,
    hp=100,
    max_hp=100,
    gifts=OTHER_GIFTS,
    favor=75,
    race="human",
    patron="mortaen",
    guest="aelora",
    archetype="warrior",
    encounter_id=ENCOUNTER,
    guest_class="mage",
    guest_favor=40,
    guest_hp=100,
    conditions=(),
):
    session = world.ctx.userdata
    lifecycle = _live_party(session, *world.ids)
    for index, deity in enumerate((patron, guest)):
        await configure(
            world,
            deity,
            archetype if index == 0 else guest_class,
            index=index,
            name=("Rook", "Iris")[index],
            race=race,
            level=8,
            ac=10,
            speed=30,
            hp={"current": hp if index == 0 else guest_hp, "max": max_hp if index == 0 else 100},
            focus={"current": 10, "max": 10},
            stamina={"current": 10, "max": 10},
            resonance={"current": 0},
            equipment={"main_hand": SWORD},
            attributes={"strength": 10, "intelligence": 18, "dexterity": 10},
            divine_favor={"patron": deity, "level": favor if index == 0 else guest_favor, "max": 100},
            patron_gifts=gifts if index == 0 else {},
            conditions=list(conditions) if index == 0 else [],
        )
        session.party.members[index].resonance.current = 0
    call = game_tools(session, query_info, activate, enter_mode, declare_phase, resolve_phase, end_combat, learn)
    await call("enter_mode", mode="combat", encounter_id=encounter_id)
    try:
        yield call
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id, conn=world.pool)
        await lifecycle.aclose()


async def walk(call):
    gift = next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)
    assert (gift["tier"], gift["status"], gift["recharge"], gift["available"], gift["spent"]) == (
        "Exalted",
        "active",
        "per_session",
        True,
        False,
    )
    return await call("activate", id=gift["id"])


def active(world):
    return world.ctx.userdata.combat_state


def follower(world):
    return participant(active(world), world.ids[0])


def position(world, target=FOE):
    active(world).spatial["positions"][target] = {"x": 5, "y": 0, "z": 0}


def claw(world, **changes):
    mob = participant(active(world), FOE)
    action = next(a for a in mob.action_pool if a["name"] == "Claw")
    action.update(changes)
    validate_enemy_action_shapes([{"id": FOE, "action_pool": [action]}])
    validate_encounter_actions([{"id": FOE, "action_pool": [action]}])
    return {**attack(FOE, world.ids[0]), "action": "Claw"}


async def declare(world, call, *actions):
    actors = {action["actor_id"] for action in actions}
    await call(
        "declare_phase",
        declarations=[
            *actions,
            *(defend(p.id) for p in active(world).participants if not p.is_fallen and p.id not in actors),
        ],
    )


async def drain(world, call):
    number = active(world).round_number
    packets = []
    for _ in range(12):
        result = await call("resolve_phase")
        if isinstance(result, tuple):
            return packets, result
        packets.extend(result["packets"])
        if active(world).round_number > number:
            await reload_state(world)
            return packets, result
    raise AssertionError("Round did not wrap")


@contextmanager
def rolls(*faces, damage=10):
    with (
        patch("check_resolution.dice_roll", side_effect=(_d20(face) for face in faces)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(damage)),
        patch("combat_enemy_action.dice_roll", return_value=_damage_die(damage)),
        patch("combat_turn_start.dice_roll", return_value=_damage_die(damage)),
        patch("dice.roll", return_value=_damage_die(damage)),
    ):
        yield


def events(world):
    return published_payloads(world.ctx.userdata.room)


async def snapshot(world):
    live = active(world).to_dict()
    saved = (await reload_state(world)).to_dict()
    assert live == saved
    return await row(world, 0), saved, events(world)


async def survivor(world, hp=1):
    await reload_state(world)
    p = follower(world)
    assert (p.hp_current, p.is_fallen, p.is_dead, p.death_save_failures, p.death_save_successes) == (
        hp,
        False,
        False,
        0,
        0,
    )
    assert (await row(world, 0))["hp"]["current"] == hp


def attack_event(world, name):
    return next(e for e in reversed(events(world)) if e.get("roll_type") == "attack" and e["attacker"] == name)


async def incoming_spell(world, spell_id, dtype):
    async with fight(world, hp=3, guest_class="druid" if dtype == "cold" else "mage") as call:
        host, guest = world.ids
        await character_spells.record_learned(guest, spell_id, "training", is_prepared=True, conn=world.pool)
        position(world)
        await checkpoint(world)
        await walk(call)
        targets = [host] * 4 if dtype == "force" else [FOE]
        await declare(
            world,
            call,
            {
                "kind": "ability",
                "actor_id": guest,
                "action": spell_id,
                "targets": targets,
                "argument_type": "",
            },
        )
        with rolls(*([7] * 4)):
            packets, _ = await drain(world, call)
        cast = next(p["cast"] for p in packets if p["actor_id"] == guest)
        receipt = next(r for r in cast["damage_results"] if r["target_id"] == host)
        assert (receipt["damage"], receipt["target_fallen"]) == (40 if dtype == "force" else 10, False)
        if dtype == "cold":
            assert [(c["damage_type"], c["damage"]) for c in receipt["damage_components"]] == [
                ("bludgeoning", 0),
                ("cold", 10),
            ]
        else:
            assert receipt["damage_type"] == dtype
        await survivor(world)


async def field_damage(world, encounter, enemy):
    async with fight(world, hp=3, encounter_id=encounter) as call:
        host = world.ids[0]
        await walk(call)
        is_mawling = enemy == "mawling_pack_adult"
        if is_mawling:
            position(world, enemy)
            await checkpoint(world)
            await declare(world, call, {**attack(enemy, host), "action": "Lunge"})
            with rolls(18, 15, 7, damage=0):
                await drain(world, call)
            assert any(c["type"] == "grappled" for c in follower(world).conditions)
        await declare(world, call)
        with rolls(7, 7):
            packets, _ = await drain(world, call)
        effects = (
            (p for p in packets if p.get("automatic"))
            if is_mawling
            else (e for p in packets if p["actor_id"] == host for e in p.get("turn_start_effects", []))
        )
        [receipt] = effects
        assert (receipt["damage"], receipt["damage_type"], receipt["target_fallen"]) == (10, "necrotic", False)
        await survivor(world)


async def reflected_bolt(world):
    async with fight(world, hp=3, archetype="mage", encounter_id="hollow_choir") as call:
        host = world.ids[0]
        await character_spells.record_learned(host, "arcane_bolt", "training", is_prepared=True, conn=world.pool)
        await declare(world, call, {"kind": "interact", "actor_id": host, "action": "choir_search_arcana"})
        with rolls(*([20] * 8)):
            _, revealed = await drain(world, call)
        assert isinstance(revealed, dict) and revealed["choir"]["phase"] == "exposed"
        await walk(call)
        await declare(
            world,
            call,
            {
                "kind": "ability",
                "actor_id": host,
                "action": "arcane_bolt",
                "targets": ["choir_zone"],
                "argument_type": "",
            },
        )
        with rolls(7, 7, 7, 15):
            packets, _ = await drain(world, call)
        cast = next(p["cast"] for p in packets if p["actor_id"] == host)
        receipt = cast["damage_result"]
        assert cast["target_id"] == host
        assert (receipt["damage"], receipt["damage_type"], receipt["target_fallen"]) == (14, "force", False)
        assert receipt["context"] != "killing_blow"
        await survivor(world)


async def serenity_touch(world):
    async with fight(world, hp=3, encounter_id="hollow_still") as call:
        host = world.ids[0]
        record = active(world).still_encounter
        assert record is not None
        facts = still_encounter.facts(active(world))
        assert facts is not None
        search = facts["search_actions"][0]
        await call("declare_phase", declarations=[{"kind": "interact", "actor_id": host, "action": search["action"]}])
        with rolls(20):
            await drain(world, call)
        await call("declare_phase", declarations=[attack(host, record["anchor_ids"][0])])
        with rolls(1):
            await drain(world, call)
        owner = record["owner_id"]
        active(world).spatial["positions"][host] = active(world).spatial["positions"][owner]
        await checkpoint(world)
        await walk(call)
        await call("declare_phase", declarations=[{**attack(owner, host), "action": "Serenity's Touch"}])
        with rolls(7):
            packets, _ = await drain(world, call)
        receipt = next(p for p in packets if p.get("action") == "Serenity's Touch")
        assert (receipt["damage"], receipt["damage_type"], receipt["charmed"]) == (10, "psychic", True)
        await survivor(world)
