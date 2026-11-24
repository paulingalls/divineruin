"""Hold the Crossing through registered death saves and Fate settlement."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _patron_engine_fixtures import configure
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from sample_fixtures import published_payloads
from test_encounter_facts_damage import GOBLIN, Fight, fight, goblin_strike
from test_encounter_facts_heal import save
from voice_condition_fixtures import participant, place_actors

import db_mutations
from _gods_content import load_gods
from activate_tools import activate
from combat_death_save import request_death_save
from combat_participant import CombatParticipant

CLAUSE = "mortaen_hold_the_crossing"


def down(actor: CombatParticipant) -> None:
    actor.hp_current = 0
    actor.is_fallen = True


def assert_receipt(receipt: dict, face: int, bonus: int, rally: int) -> None:
    assert (receipt["roll"], receipt["bonus"], receipt["synergy_bonus"], receipt["synergy_clause_id"]) == (
        face,
        bonus,
        rally,
        CLAUSE if rally else None,
    )


async def check_save(f: Fight, roller: str, face: int, bonus: int, rally: int, *, success: bool) -> None:
    call = game_tools(f.session, request_death_save)
    receipt = await save(call, roller, face)
    assert receipt["success"] is success
    assert_receipt(receipt, face, bonus, rally)
    state = await f.reload()
    saved = participant(state, roller)
    assert (saved.death_save_successes, saved.death_save_failures) == (int(success), int(not success))
    assert state.encounter_facts["death_save_success_round"] == ({roller: state.round_number} if success else {})


async def hold_the_crossing(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        await f.round(goblin_strike(GOBLIN, f.ally))
        ally = participant(f.session.combat_state, f.ally)
        assert ally.is_fallen and ally.hp_current == 0
        await check_save(f, f.ally, 9, 1, 1, success=True)
        marshal = participant(f.session.combat_state, f.hero)
        assert (marshal.death_save_successes, marshal.death_save_failures) == (0, 0)

    mortaen = next(g for g in load_gods() if g["god_id"] == "mortaen")
    assert mortaen["layer_4_synergy_matrix"]["marshal"] == {
        "name": "Hold the Crossing",
        "type": "divine",
        "clauses": [
            {
                "effect": "Allies at 0 HP within earshot gain +1 to death saving throws.",
                "status": "active",
                "resolution": "engine",
                "implementation_id": CLAUSE,
            }
        ],
    }


SCENARIOS = {CLAUSE: ("patron_synergy_combat:marshal_death_save_bonus", hold_the_crossing, [()])}


async def test_death_save_without_a_marshal(world: SimpleNamespace) -> None:
    async with fight(world, "thyra") as f:
        await f.round(goblin_strike(GOBLIN, f.ally))
        await check_save(f, f.ally, 9, 0, 0, success=False)


@pytest.mark.parametrize(
    "patron,archetype,source_state",
    [
        ("mortaen", "marshal", "fallen"),
        ("mortaen", "marshal", "dead"),
        ("thyra", "marshal", "standing"),
        ("mortaen", "warrior", "standing"),
        ("mortaen", "marshal", "echo"),
    ],
    ids=["fallen", "dead", "thyra-marshal", "mortaen-warrior", "hostile-echo"],
)
async def test_ineligible_source(world: SimpleNamespace, patron: str, archetype: str, source_state: str) -> None:
    async with fight(world, patron, archetype=archetype) as f:
        state = f.session.combat_state
        source = participant(state, f.hero)
        if source_state in ("fallen", "dead"):
            down(source)
            source.is_dead = source_state == "dead"
        elif source_state == "echo":
            source.type = "temporary_hollowed"
        down(participant(state, f.ally))
        await check_save(f, f.ally, 9, 0, 0, success=False)


@pytest.mark.parametrize("face,success", [(8, True), (7, False)])
async def test_marshal_keeps_only_personal_bonus_without_another_marshal_in_combat(
    world: SimpleNamespace, face: int, success: bool
) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        await configure(world, "mortaen", "marshal", index=1)
        state = f.session.combat_state
        state.participants.remove(participant(state, f.ally))
        state.initiative_order.remove(f.ally)
        place_actors(state)
        down(participant(state, f.hero))
        await check_save(f, f.hero, face, 2, 0, success=success)


@pytest.mark.parametrize("face,success", [(7, True), (6, False)])
async def test_marshal_bonus_adds_to_personal_bonus(world: SimpleNamespace, face: int, success: bool) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        await configure(world, "mortaen", "warrior", index=1)
        down(participant(f.session.combat_state, f.ally))
        await check_save(f, f.ally, face, 3, 1, success=success)


async def test_two_marshals_give_the_companion_one_bonus(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        await configure(world, "mortaen", "marshal", index=1)
        state = f.session.combat_state
        participant(state, f.ally).archetype_id = "marshal"
        companion = CombatParticipant(
            id="kael", name="Kael", type="companion", initiative=10, hp_current=0, hp_max=20, ac=14, is_fallen=True
        )
        state.participants.append(companion)
        state.initiative_order.append(companion.id)
        place_actors(state)
        await check_save(f, companion.id, 9, 1, 1, success=True)


async def test_destroyed_echo_receives_no_bonus(world: SimpleNamespace) -> None:
    async with fight(world, "mortaen", archetype="marshal") as f:
        echo = participant(f.session.combat_state, f.ally)
        echo.type = "temporary_hollowed"
        down(echo)
        await check_save(f, echo.id, 9, 0, 0, success=False)


@pytest.mark.parametrize("flip", [False, True], ids=["fates-thread", "lucky"])
async def test_fate_settles_with_the_marshal_bonus(world: SimpleNamespace, flip: bool) -> None:
    async with fight(world, "zhael", archetype="mage") as f:
        await configure(world, "zhael", "mage", hp={"current": 0, "max": 20}, patron_gifts={})
        await configure(world, "mortaen", "marshal", index=1)
        state = f.session.combat_state
        participant(state, f.ally).archetype_id = "marshal"
        down(participant(state, f.hero))
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
        call = game_tools(f.session, request_death_save, activate)
        original, kept = (1, 20) if flip else (5, 9)
        with patch("combat_resolution.dice_roll", side_effect=[_d20(original), *([] if flip else [_d20(kept)])]):
            offer = (await call("request_death_save", player_id=f.hero))["fate_offer"]
            assert (offer["die"], offer["total"]) == (original, original + 1)
            stored = await db_mutations.load_combat_state(state.combat_id)
            faller = participant(stored, f.hero)
            assert faller.is_fallen and faller.hp_current == 0
            assert (faller.death_save_successes, faller.death_save_failures) == (0, 0)
            assert published_payloads(f.session.room) == []

            args = {"id": "zhael_lucky" if flip else "zhael_fates_thread", "offer_id": offer["offer_id"]}
            if flip:
                receipt = await call("activate", **args)
            else:
                shown = await call("activate", **args)
                assert shown["reroll"] == {"die": 9, "total": 10}
                receipt = await call("activate", **args, keep="reroll")

        assert receipt["success"] and receipt["revived"] is flip
        assert_receipt(receipt, kept, 1, 1)
        saved = participant(await f.reload(), f.hero)
        assert (saved.death_save_successes, saved.death_save_failures) == (int(not flip), 0)
        assert saved.hp_current == int(flip)
        if flip:
            assert (await row(world, 0))["hp"]["current"] == 1
        rolls = [
            event["roll"] for event in published_payloads(f.session.room) if event.get("roll_type") == "death_save"
        ]
        assert rolls == [kept]
