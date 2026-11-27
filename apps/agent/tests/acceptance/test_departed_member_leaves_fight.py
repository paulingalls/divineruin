import json
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import TypeVar
from unittest.mock import MagicMock, patch

import pytest
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.disruption_reactions_harness import open_stage
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

from check_resolution import D20Roll
from combat_state import CombatState

T = TypeVar("T")


def assert_departed(state: CombatState, guest: str) -> None:
    assert state.get_participant(guest) is None and state.spatial is not None
    assert guest not in (*state.initiative_order, *state.pending_declarations, *state.spatial["positions"])
    assert guest not in state.spatial["speeds"]


@asynccontextmanager
async def authorized(fight, guest: str):
    lifecycle = _live_party(fight.sd, *fight.players)
    await lifecycle.authorize(guest)
    try:
        yield
    finally:
        await lifecycle.aclose()


@asynccontextmanager
async def departed(fight, guest: str):
    async with authorized(fight, guest):
        await leave(fight.sd, guest, room_io=MagicMock())
        yield


def d20(face: int):
    return patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(face))


async def declare(fight, *declarations: dict) -> dict:
    return await fight.command("declare_phase", {"declarations": list(declarations)})


async def defend_all(fight) -> None:
    state = await fight.reload()
    await declare(fight, *({"kind": "defend", "actor_id": p.id, "reshape": []} for p in state.participants))


def present(value: T | None) -> T:
    assert value is not None
    return value


def swing(enemy: str, target: str) -> dict:
    return {"actor_id": enemy, **strike(target, action=SWORD)}


async def saved_wounds(player_id: str) -> tuple:
    row = await player_row(player_id)
    return row["hp"], row.get("conditions")


def target_left(packets: list[dict]) -> list[tuple]:
    return [(p["actor_id"], p["target_id"], p["resolved"]) for p in packets if p.get("outcome") == "target_left"]


@pytest.mark.parametrize("stage", ["pre_roll", "post_roll"])
@pytest.mark.parametrize("departing_index", [0, 1])
async def test_held_departure_cancels_only_the_guest_strike(reset_db_pool, stage: str, departing_index: int) -> None:
    roles = ("artificer", "guardian") if departing_index == 0 else ("guardian", "artificer")
    library = ((departing_index, "arcane_shield_spell"),)
    async with defense_fight(roles[0], ally_archetype=roles[1], library=library) as fight:
        guest, host = fight.players[departing_index], fight.players[1 - departing_index]
        first, second = fight.enemies
        await declare(fight, swing(first, guest), swing(second, host))
        with d20(16):
            assert (await open_stage(fight, stage))["target_id"] == guest
            guest_before, host_hp = await saved_wounds(guest), (await player_row(host))["hp"]["current"]
            history = deepcopy((await fight.reload()).round_checkpoints)
            async with departed(fight, guest):
                assert (await fight.reload()).round_checkpoints == history and fight.sd.primary_player_id == host
                packets = []
                for _ in range(8):
                    if (await fight.reload()).round_number == 2:
                        break
                    receipt = await tool_receipt(fight, host, "resolve_phase", {})
                    assert not receipt.is_error, receipt.output
                    packets.extend(json.loads(receipt.output)["packets"])
                state = await fight.reload()
                assert state.round_number == 2 and target_left(packets) == [(first, guest, False)]
                assert any(p["actor_id"] == second and p.get("damage", 0) > 0 for p in packets)
                assert (await player_row(host))["hp"]["current"] < host_hp
                assert await saved_wounds(guest) == guest_before
                assert_departed(state, guest)
                assert state.round_checkpoints[0] == history[-1]


async def test_declaration_departure_drops_the_guest_turn_and_incoming_strike(reset_db_pool) -> None:
    from acceptance.test_martial_core_kit import weapon_attack

    from db_mutations_conditions import save_player_conditions

    async with defense_fight("warrior") as fight:
        host, guest = fight.players
        first, second = fight.enemies
        await save_player_conditions(guest, [{"type": "poisoned", "source": "poison test fixture", "duration": None}])
        history = deepcopy((await fight.reload()).round_checkpoints)
        own, incoming = weapon_attack(guest, first, ""), swing(second, guest)
        await declare(fight, own, swing(first, host), incoming)
        before, first_hp = await player_row(guest), participant(await fight.reload(), first).hp_current
        async with departed(fight, guest):
            state = await fight.reload()
            assert state.round_checkpoints == history
            assert_departed(state, guest)
            with d20(16):
                packets = await fight.drain()
            assert all(p["actor_id"] != guest for p in packets) and target_left(packets) == [(second, guest, False)]
            assert any(p["actor_id"] == first and p.get("damage", 0) > 0 for p in packets)
            assert participant(await fight.reload(), first).hp_current == first_hp
            refusal = await fight.command("declare_phase", {"declarations": [incoming]}, error=True)
            assert "Unknown target" in refusal and guest in refusal
            state = await fight.reload()
            for enemy in fight.enemies:
                participant(state, enemy).hp_current, participant(state, enemy).is_fallen = 0, True
            await fight.persist()
            await fight.command("end_combat", {"outcome": "victory"})
            assert await player_row(guest) == before


@pytest.mark.parametrize("leaver_role", ["patient", "marshal", "both"])
async def test_field_medic_declaration_survives_departure(reset_db_pool, leaver_role: str) -> None:
    from acceptance.test_valdris_party_yield import ability_action

    import ability_persistence
    import db_mutations
    import db_queries

    async with defense_fight("warrior", ally_archetype="marshal", extra_archetypes=("guardian",)) as fight:
        host, marshal, patient = fight.players
        foe, item_id = fight.enemies[0], "healing_potion_minor"
        patient = marshal if leaver_role == "both" else patient
        await db_mutations.add_inventory_item(host, item_id, 1, tainted=False)
        await ability_persistence.set_elective_equipped(marshal, "marshal_field_medic_order", equipped=True)
        await declare(fight, ability_action(marshal, "marshal_field_medic_order", host))
        await fight.drain()
        swing = {"kind": "attack_consume", "actor_id": host, "action": "Longsword", "target_id": foe}
        await declare(fight, {**swing, "item_id": item_id, "heal_target_id": patient})
        patient_hp, foe_hp = (await player_row(patient))["hp"], participant(await fight.reload(), foe).hp_current
        async with departed(fight, patient if leaver_role == "patient" else marshal):
            with d20(16):
                packets = await fight.drain()
            final_hp = participant(await fight.reload(), foe).hp_current
            if leaver_role == "marshal":
                assert final_hp < foe_hp and all("field_medic" not in p for p in packets)
            else:
                assert target_left(packets) == [(host, patient, False)] and final_hp == foe_hp
            assert (await player_row(patient))["hp"] == patient_hp
            (potion,) = [p for p in await db_queries.get_player_inventory(host) if p["id"] == item_id]
            assert potion["slot_info"]["quantity"] == 1
