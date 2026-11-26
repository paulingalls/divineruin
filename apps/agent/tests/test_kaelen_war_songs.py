"""War Songs through registered phase verbs and persisted combat state."""

import random
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import attack, game_tools
from acceptance._capstone_helpers import _d20, _damage_die
from sample_fixtures import make_context
from test_aelora_gift import _live_party
from test_encounter_facts_damage import GOBLIN, Fight, fight
from voice_condition_fixtures import participant, place_actors
from weapon_fixtures import DAGGER

import db_mutations
from _gods_content import load_gods
from activate_tools import activate
from check_tools import check
from combat_end import end_combat
from combat_turn import resolve_phase
from dice import DiceResult, roll
from mode_tools import enter_mode
from session_data import SessionData

CLAUSE = "kaelen_war_songs"
UPGRADE = "inspire_attack_upgrade"
FACE = 8


class MaxDie(random.Random):
    def randint(self, a: int, b: int) -> int:
        return b


@contextmanager
def bonus_rolls() -> Iterator[list[tuple[str, int]]]:
    rolls: list[tuple[str, int]] = []

    def capture(notation: str, *, rng: object) -> DiceResult:
        result = roll(notation, rng=MaxDie())
        rolls.append((notation, result.total))
        return result

    with patch("condition_bonus.dice_roll", side_effect=capture):
        yield rolls


def inspire(actor: str, ability: str, *targets: str) -> dict:
    return {"kind": "ability", "actor_id": actor, "action": ability, "targets": list(targets), "argument_type": ""}


def inspired(f: Fight, bearer: str) -> list[dict]:
    return [c for c in participant(f.session.combat_state, bearer).conditions if c["type"] == "inspired"]


async def land(f: Fight, actor: str, ability: str, *targets: str, upgrade: bool) -> None:
    packets = await f.round(inspire(actor, ability, *targets))
    assert any(p.get("condition_applied") == "inspired" for p in packets), packets
    for target in targets:
        (condition,) = inspired(f, target)
        assert (condition["source"], condition.get(UPGRADE)) == (ability, upgrade)


def assert_attack(packet: dict, rolls: list[tuple[str, int]], sides: int) -> None:
    assert rolls == [(f"1d{sides}", sides)]
    component = (sides, CLAUSE) if sides == 6 else (0, None)
    assert (packet["war_songs_bonus"], packet["war_songs_clause_id"]) == component
    assert packet["attack_total"] == FACE + 1 + sides
    assert packet["hit"] is (packet["attack_total"] >= packet["target_ac"])


async def strike(f: Fight, bearer: str, sides: int, foe: str = GOBLIN) -> dict:
    with bonus_rolls() as rolls:
        packets = await f.round(attack(bearer, foe), faces=(FACE,))
    packet = next(p for p in packets if p["actor_id"] == bearer and "attack_total" in p)
    assert_attack(packet, rolls, sides)
    assert not inspired(f, bearer)
    return packet


async def war_songs(world: SimpleNamespace) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        await land(f, f.hero, "bard_inspire", f.ally, upgrade=True)
        participant(f.session.combat_state, GOBLIN).ac = 13
        hit = await strike(f, f.ally, 6)
        assert hit["hit"] and hit["target_ac"] == 15
        with bonus_rolls() as rolls:
            packets = await f.round(attack(f.ally, GOBLIN), faces=(FACE,))
        packet = next(p for p in packets if "attack_total" in p)
        assert not rolls and not packet["hit"] and packet["war_songs_bonus"] == 0

    kaelen = next(god for god in load_gods() if god["god_id"] == "kaelen")
    bard = kaelen["layer_4_synergy_matrix"]["bard"]
    assert (bard["name"], bard["type"]) == ("War Songs", "unexpected")
    assert [(c["status"], c["resolution"], c["implementation_id"]) for c in bard["clauses"]] == [
        ("active", "engine", CLAUSE)
    ]


SCENARIOS = {CLAUSE: ("patron_synergy_combat:inspire_attack_upgrade", war_songs, [()])}


async def test_combat_refresh(world: SimpleNamespace) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        await land(f, f.hero, "bard_inspire", f.ally, upgrade=True)
        await configure(world, "valdris", "bard", index=1)
        await land(f, f.ally, "bard_inspire", f.ally, upgrade=False)
        await strike(f, f.ally, 4)


@pytest.mark.parametrize(
    "patron,archetype,ability",
    [("valdris", "bard", "bard_inspire"), ("kaelen", "diplomat", "diplomat_inspire")],
)
async def test_only_kaelen_bard_inspires_attack_upgrade(
    world: SimpleNamespace, patron: str, archetype: str, ability: str
) -> None:
    async with fight(world, patron, archetype=archetype, ally_hp=20) as f:
        await configure(world, "kaelen", "bard", index=1)
        await land(f, f.hero, ability, f.ally, upgrade=False)
        await strike(f, f.ally, 4)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"kind": "save", "save_type": "dexterity", "dc": 10, "effect_on_fail": "Stumble"}, id="save"),
        pytest.param(
            {
                "kind": "skill",
                "synergy_context": "none",
                "skill": "athletics",
                "difficulty": "easy",
                "context_description": "Lift the gate",
                "hearing_only": False,
            },
            id="check",
        ),
    ],
)
async def test_save_and_check_keep_the_d4(world: SimpleNamespace, payload: dict) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        await land(f, f.hero, "bard_inspire", f.ally, upgrade=True)
        lifecycle = _live_party(f.session, *world.ids)
        try:
            with (
                f.session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized),
                patch("check_resolution.dice_roll", return_value=_d20(10)),
                bonus_rolls() as rolls,
            ):
                result = await game_tools(f.session, check)("check", roll=payload)
        finally:
            await lifecycle.aclose()
        assert rolls == [("1d4", 4)]
        assert result["total"] == 14
        assert "war_songs_bonus" not in result and "war_songs_clause_id" not in result
        await f.reload()
        assert not inspired(f, f.ally)


async def test_mass_inspire(world: SimpleNamespace) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        await configure(world, "kaelen", "bard", level=9)
        await land(f, f.hero, "bard_mass_inspire", f.hero, f.ally, upgrade=True)
        for bearer in (f.hero, f.ally):
            await strike(f, bearer, 6)


def fresh_session(world: SimpleNamespace) -> SessionData:
    return make_context(player_id=world.ids[0], party_member_ids=world.ids[1:], room=world.ctx.userdata.room).userdata


async def test_exploration_inspire_survives_combat_hydration(world: SimpleNamespace) -> None:
    for index, (patron, archetype) in enumerate((("kaelen", "bard"), ("thyra", "warrior"))):
        await configure(
            world,
            patron,
            archetype,
            index=index,
            name=f"Player {index}",
            ac=14,
            speed=30,
            hp={"current": 20, "max": 20},
            attributes={"strength": 10, "dexterity": 10},
            equipment={"main_hand": DAGGER},
        )
    host, guest = world.ids
    await game_tools(world.ctx.userdata, activate)("activate", id="bard_inspire", target_id=guest)
    (condition,) = (await row(world, 1))["conditions"]
    assert (condition["source"], condition.get(UPGRADE)) == ("bard_inspire", True)

    session = fresh_session(world)
    lifecycle = _live_party(session, host, guest)
    f = Fight(SimpleNamespace(ids=world.ids, ctx=SimpleNamespace(userdata=session)))
    try:
        await game_tools(session, enter_mode)("enter_mode", mode="combat", encounter_id="ruins_mawling_pair")
        state = session.combat_state
        assert state is not None
        f.combat_id = state.combat_id
        assert inspired(f, guest) == [condition]
        place_actors(state)
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        await f.reload()
        await strike(f, guest, 6, foe="mawling_1")
        await game_tools(session, end_combat)("end_combat", outcome="fled")
        assert not any(c["type"] == "inspired" for c in (await row(world, 1)).get("conditions", []))
    finally:
        if session.combat_state is not None:
            await db_mutations.delete_combat_state(session.combat_state.combat_id)
        await lifecycle.aclose()


@pytest.mark.parametrize("settlement", ["activate", "fresh", "legacy"])
async def test_keep_original_after_reload(world: SimpleNamespace, settlement: str) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        await land(f, f.hero, "bard_inspire", f.ally, upgrade=True)
        await configure(world, "zhael", "warrior", index=1)
        session = f.session
        lifecycle = _live_party(session, *world.ids)
        try:
            await f.declare(attack(f.ally, GOBLIN))
            with patch("check_resolution.dice_roll", return_value=_d20(FACE)), bonus_rolls() as rolls:
                pending = await f.call("resolve_phase")
            offer = pending["fate_offer"]
            assert pending["beat"] == "resolution" and offer["roller_id"] == f.ally
            assert rolls == [("1d6", 6)]
            state = await f.reload()
            assert participant(state, GOBLIN).hp_current == 50
            assert state.ally_continuation is not None
            prepared = state.ally_continuation["attack"]["prepared"]
            assert (prepared["war_songs_bonus"], prepared["war_songs_clause_id"]) == (6, CLAUSE)
            if settlement == "legacy":
                del prepared["war_songs_bonus"], prepared["war_songs_clause_id"]
                await db_mutations.save_combat_state(f.combat_id, state.to_dict())

            with (
                patch("condition_bonus.dice_roll", side_effect=AssertionError("rolled the stored bonus again")),
                patch("check_resolution_attack.dice_roll", return_value=_damage_die(5)),
            ):
                if settlement == "activate":
                    with session._bind_authenticated_actor(f.ally, 1, lifecycle.require_authorized):
                        result = await f.call(
                            "activate", id="zhael_fates_thread", offer_id=offer["offer_id"], keep="original"
                        )
                else:
                    result = await resume_original(world, f.combat_id)
        finally:
            await lifecycle.aclose()
        packet = next(p for p in result["packets"] if p["actor_id"] == f.ally and "attack_total" in p)
        assert (packet["roll"], packet["attack_total"], packet["damage"]) == (FACE, FACE + 1 + 6, 5)
        expected = (0, None) if settlement == "legacy" else (6, CLAUSE)
        assert (packet["war_songs_bonus"], packet["war_songs_clause_id"]) == expected
        saved = await f.reload()
        assert participant(saved, GOBLIN).hp_current == 45 and not inspired(f, f.ally)


async def resume_original(world: SimpleNamespace, combat_id: str) -> dict:
    fresh = fresh_session(world)
    fresh.combat_state = await db_mutations.load_combat_state(combat_id)
    lifecycle = _live_party(fresh, *world.ids)
    try:
        return await game_tools(fresh, resolve_phase)("resolve_phase")
    finally:
        await lifecycle.aclose()


async def test_legacy_inspired_condition(world: SimpleNamespace) -> None:
    async with fight(world, "kaelen", archetype="bard", ally_hp=20) as f:
        state = f.session.combat_state
        participant(state, f.ally).conditions = [
            {"type": "inspired", "source": "bard_inspire", "duration": None, "stacks": 1}
        ]
        await db_mutations.save_combat_state(f.combat_id, state.to_dict())
        await f.reload()
        await strike(f, f.ally, 4)
