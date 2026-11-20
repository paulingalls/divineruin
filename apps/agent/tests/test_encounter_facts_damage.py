"""Encounter damage clauses at the registered combat and checkpoint boundaries."""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import asyncpg
import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, defend, game_tools
from acceptance._capstone_helpers import _build_state, _d20, _damage_die, _enemy, _player
from combat.test_handle_hp_zero import _hollowed
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant, place_actors

import check_resolution_attack
import db_mutations
from _gods_content import load_gods
from activate_tools import activate
from combat_attack_roll import deserialize_roll, serialize_roll
from combat_damage_results import freeze_blow, thaw_blow
from combat_state import CombatState
from combat_turn import declare_phase, resolve_phase
from query_tools import query_info

MORTAEN = "mortaen_last_vigil"
ZHAEL = "zhael_threaded_blade"
GOBLIN, OTHER = "goblin_one", "goblin_two"
EMPTY = {"ally_downers": [], "misses": {}, "once_spent": {}}


@contextmanager
def dice(*faces: int) -> Iterator[None]:
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)),
    ):
        yield


class Fight:
    def __init__(self, world: SimpleNamespace) -> None:
        self.hero, self.ally = world.ids
        self.session = world.ctx.userdata
        self.call = game_tools(self.session, declare_phase, resolve_phase, activate, query_info)
        self.combat_id = self.hero

    async def reload(self) -> CombatState:
        saved = await db_mutations.load_combat_state(self.combat_id)
        assert saved is not None
        self.session.combat_state = saved
        return saved

    async def declare(self, *strikes: dict) -> None:
        actors = {strike["actor_id"] for strike in strikes}
        await self.call(
            "declare_phase",
            declarations=[
                *strikes,
                *(defend(pid) for pid in self.session.combat_state.initiative_order if pid not in actors),
            ],
        )

    async def round(self, *strikes: dict, faces: tuple[int, ...] = (15,)) -> list[dict]:
        await self.declare(*strikes)
        packets = []
        with dice(*faces):
            for _ in range(5):
                result = await self.call("resolve_phase")
                packets.extend(result.get("packets", []))
                if result["beat"] == "declaration":
                    await self.reload()
                    return packets
        raise AssertionError("round did not wrap")

    async def hit(self, clause: str | None, target: str = GOBLIN, *, weapon: str = "Longsword") -> None:
        before = participant(self.session.combat_state, target).hp_current
        packets = await self.round({**attack(self.hero, target), "action": weapon})
        packet = next(p for p in packets if p["actor_id"] == self.hero)
        damage = 6 if clause else 5
        assert packet["damage"] == damage
        assert participant(self.session.combat_state, target).hp_current == before - damage
        assert packet["synergy_clause_id"] == clause
        if clause:
            assert (packet["synergy_damage"], packet["synergy_damage_type"]) == (1, "slashing")
            receipt = [e for e in published_payloads(self.session.room) if e.get("roll_type") == "attack"][-1]
            assert (receipt["synergy_damage"], receipt["synergy_damage_type"], receipt["synergy_clause_id"]) == (
                1,
                "slashing",
                clause,
            )


@asynccontextmanager
async def fight(
    world: SimpleNamespace,
    patron: str,
    *,
    archetype: str = "warrior",
    ally_hp: int = 5,
    goblin_hp: int = 50,
    hollowed: bool = False,
    extra: bool = False,
) -> AsyncIterator[Fight]:
    f = Fight(world)
    await configure(
        world,
        patron,
        archetype,
        level=5,
        flags={"extra_attack": extra},
        patron_gifts={key: {"spent": True} for key in ("zhael_fates_thread", "zhael_lucky")},
    )
    await configure(world, "thyra", "warrior", index=1, hp={"current": ally_hp, "max": 20})
    state = _build_state(f.combat_id, f.hero, [_enemy(OTHER, 50), _enemy(GOBLIN, goblin_hp)])
    hero = participant(state, f.hero)
    hero.archetype_id, hero.level = archetype, 5
    hero.enhancers = ["extra_attack"] if extra else []
    hero.action_pool.append({"name": "Shortbow", "damage": "1d6", "damage_type": "piercing", "ranged": True})
    ally = _player(f.ally, ally_hp)
    ally.hp_max = 20
    ally.conditions = _hollowed(2) if hollowed else []
    state.participants.append(ally)
    state.initiative_order.insert(1, f.ally)
    place_actors(state)
    f.session.combat_state = state
    try:
        yield f
    finally:
        await db_mutations.delete_combat_state(f.combat_id)


def goblin_strike(attacker: str, ally: str) -> dict:
    return {**attack(attacker, ally), "action": "Scimitar"}


async def catalog_clause(f: Fight, patron: str, clause: str) -> None:
    authored = next(g for g in load_gods() if g["god_id"] == patron)["layer_4_synergy_matrix"]["warrior"]
    assert (await f.call("query_info", kind="patron"))["synergy"] == authored
    assert authored["type"] == "divine"
    assert [(c["status"], c["resolution"], c.get("implementation_id")) for c in authored["clauses"]] == [
        ("active", "engine", clause)
    ]


async def mortaen_vigil(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen") as f:
        await f.round(goblin_strike(GOBLIN, f.ally))
        assert participant(f.session.combat_state, f.ally).hp_current == 0
        await f.hit(MORTAEN)
        assert f.session.combat_state.encounter_facts == {**EMPTY, "ally_downers": [GOBLIN]}
        await catalog_clause(f, "mortaen", MORTAEN)


async def zhael_blade(world: SimpleNamespace) -> None:
    async with fight(world, "zhael") as f:
        for _ in range(2):
            await f.round(attack(f.hero, GOBLIN), faces=(1,))
        assert f.session.combat_state.encounter_facts["misses"] == {f.hero: [GOBLIN]}
        await f.hit(ZHAEL)
        assert f.session.combat_state.encounter_facts["once_spent"] == {ZHAEL: [f.hero]}
        await f.hit(None)
        assert f.session.combat_state.encounter_facts["once_spent"] == {ZHAEL: [f.hero]}
        await catalog_clause(f, "zhael", ZHAEL)


IMPLEMENTATION = "patron_synergy_combat:encounter_damage_clause"
SCENARIOS = {MORTAEN: (IMPLEMENTATION, mortaen_vigil, [()]), ZHAEL: (IMPLEMENTATION, zhael_blade, [()])}


@pytest.mark.parametrize("control", ["other", "kaelen", "hollowed", "already_fallen", "hostile_fall"])
async def test_vigil_controls(world: SimpleNamespace, control: str) -> None:
    async with fight(
        world,
        "kaelen" if control == "kaelen" else "mortaen",
        ally_hp=10 if control == "other" else 5,
        goblin_hp=5 if control == "hostile_fall" else 50,
        hollowed=control == "hollowed",
    ) as f:
        if control == "hostile_fall":
            await f.round(attack(f.hero, GOBLIN))
            assert participant(f.session.combat_state, GOBLIN).is_fallen
        elif control == "other":
            await f.round(goblin_strike(OTHER, f.ally), goblin_strike(GOBLIN, f.ally), faces=(15, 15))
        else:
            await f.round(goblin_strike(GOBLIN, f.ally))
        if control == "already_fallen":
            packets = await f.round(goblin_strike(OTHER, f.ally))
            assert any(p.get("hit") for p in packets if p["actor_id"] == OTHER)
        if control == "hollowed":
            assert participant(f.session.combat_state, f.ally).type == "temporary_hollowed"
        assert f.session.combat_state.encounter_facts["ally_downers"] == (
            [] if control in ("hollowed", "hostile_fall") else [GOBLIN]
        )
        if control in ("other", "kaelen", "hollowed"):
            await f.hit(None, OTHER if control == "other" else GOBLIN)


@pytest.mark.parametrize("control", ["ranged", "other_target", "other_attacker", "non_warrior"])
async def test_blade_controls(world: SimpleNamespace, control: str) -> None:
    async with fight(world, "zhael", archetype="mage" if control == "non_warrior" else "warrior") as f:
        await f.round(attack(f.ally if control == "other_attacker" else f.hero, GOBLIN), faces=(1,))
        await f.hit(
            None,
            OTHER if control == "other_target" else GOBLIN,
            weapon="Shortbow" if control == "ranged" else "Longsword",
        )
        assert f.session.combat_state.encounter_facts["once_spent"] == {}
        if control != "non_warrior":
            if control == "other_attacker":
                await f.round(attack(f.hero, GOBLIN), faces=(1,))
            await f.hit(ZHAEL)


async def test_blade_extra_attack(world: SimpleNamespace) -> None:
    async with fight(world, "zhael", extra=True) as f:
        packets = await f.round(attack(f.hero, GOBLIN), faces=(1, 15))
        packet = next(p for p in packets if p["actor_id"] == f.hero)
        assert [s["damage"] for s in packet["attacks"]] == [0, 6]
        assert (packet["synergy_damage"], packet["synergy_clause_id"]) == (1, ZHAEL)
        assert f.session.combat_state.encounter_facts["once_spent"] == {ZHAEL: [f.hero]}


async def test_blade_fate_hold(world: SimpleNamespace) -> None:
    async with fight(world, "zhael") as f:
        await f.round(attack(f.hero, GOBLIN), faces=(1,))
        await configure(world, "zhael", "warrior", patron_gifts={"zhael_lucky": {"spent": True}})
        await f.declare(attack(f.hero, GOBLIN))
        with dice(15):
            offer = (await f.call("resolve_phase"))["fate_offer"]
            held = await f.reload()
            assert participant(held, GOBLIN).hp_current == 50
            assert held.encounter_facts["once_spent"] == {}
            settled = await f.call("activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original")
        assert settled["packets"][0]["synergy_clause_id"] == ZHAEL
        saved = await f.reload()
        assert participant(saved, GOBLIN).hp_current == 44
        assert saved.encounter_facts["once_spent"] == {ZHAEL: [f.hero]}


@pytest.mark.parametrize("fact", list(EMPTY))
async def test_fact_rolls_back(world: SimpleNamespace, fact: str) -> None:
    async with fight(world, "zhael") as f:
        if fact == "once_spent":
            await f.round(attack(f.hero, GOBLIN), faces=(1,))
        fall = fact == "ally_downers"
        await f.declare(goblin_strike(GOBLIN, f.ally) if fall else attack(f.hero, GOBLIN))
        if fall:
            await f.call("resolve_phase")
        before = (await f.reload()).to_dict()
        expected = {"ally_downers": [GOBLIN], "misses": {f.hero: [GOBLIN]}, "once_spent": {ZHAEL: [f.hero]}}
        save = db_mutations.save_combat_state

        async def abort(combat_id: str, data: dict, *, conn: asyncpg.Connection | None = None) -> None:
            await save(combat_id, data, conn=conn)
            assert data["encounter_facts"][fact] == expected[fact]
            await (conn or world.pool).execute("SELECT 1 / 0")

        with (
            patch.object(db_mutations, "save_combat_state", side_effect=abort) as attempted,
            dice(1 if fact == "misses" else 15),
            pytest.raises(asyncpg.DivisionByZeroError),
        ):
            await f.call("resolve_phase")
        attempted.assert_awaited_once()
        assert f.session.combat_state.to_dict() == before
        assert (await f.reload()).to_dict() == before


async def test_legacy_checkpoint(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen") as f:
        state = f.session.combat_state
        data = state.to_dict()
        data.pop("encounter_facts", None)
        await db_mutations.save_combat_state(f.combat_id, data)
        loaded = await f.reload()
        assert loaded.encounter_facts == EMPTY
        fresh = CombatState("fresh", [], [])
        other = CombatState("other", [], [])
        for key in EMPTY:
            assert fresh.encounter_facts[key] is not other.encounter_facts[key]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        42,
        [],
        {"misses": {}, "once_spent": {}},
        {**EMPTY, "extra": []},
        *({**EMPTY, "ally_downers": bad} for bad in ({}, [3], [" "])),
        *(
            {**EMPTY, field: bad}
            for field in ("misses", "once_spent")
            for bad in ([], {" ": []}, {1: []}, {"actor": {}}, {"actor": [None]}, {"actor": [" "]})
        ),
    ],
)
def test_malformed_checkpoint(bad: object) -> None:
    data = CombatState("malformed", [], []).to_dict()
    with pytest.raises(ValueError, match="encounter_facts"):
        CombatState.from_dict({**data, "encounter_facts": bad})


@pytest.mark.parametrize("format_", ["roll", "blow"])
def test_held_roll_component(format_: str) -> None:
    with dice(15):
        action = _player("hero").action_pool[0]
        result = check_resolution_attack.resolve_attack({"encounter_damage_clause": ZHAEL}, action, 10, 50)
    if format_ == "roll":
        payload, read, key, index = serialize_roll(result, 10), deserialize_roll, "attack_result", 0
    else:
        payload, read, key, index = freeze_blow(action, result, 10), thaw_blow, "fields", 1
    restored = read(json.loads(json.dumps(payload)))[index]
    assert isinstance(restored, check_resolution_attack.AttackResult)
    assert (restored.damage, restored.synergy_damage, restored.synergy_clause_id) == (6, 1, ZHAEL)
    del payload[key]["synergy_clause_id"]
    legacy = read(json.loads(json.dumps(payload)))[index]
    assert isinstance(legacy, check_resolution_attack.AttackResult)
    assert (legacy.damage, legacy.synergy_damage, legacy.synergy_clause_id) == (6, 1, None)
