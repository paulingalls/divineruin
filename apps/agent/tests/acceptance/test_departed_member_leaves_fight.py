import json
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.disruption_reactions_harness import open_stage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

from check_resolution import D20Roll
from combat_state import CombatState
from participant_lifecycle import PartyLifecycle


def assert_departed(state: CombatState, guest: str) -> None:
    assert state.get_participant(guest) is None
    assert guest not in state.initiative_order
    assert guest not in state.pending_declarations
    assert state.spatial is not None
    assert guest not in state.spatial["positions"]
    assert guest not in state.spatial["speeds"]


async def depart(fight: MawlingHarness, guest: str) -> PartyLifecycle:
    lifecycle = _live_party(fight.sd, *fight.players)
    await lifecycle.authorize(guest)
    await leave(fight.sd, guest, room_io=MagicMock())
    return lifecycle


@pytest.mark.parametrize("stage", ["pre_roll", "post_roll"])
@pytest.mark.parametrize("departing_index", [0, 1])
async def test_held_departure_cancels_only_the_guest_strike(reset_db_pool, stage: str, departing_index: int) -> None:
    roles = ("artificer", "guardian") if departing_index == 0 else ("guardian", "artificer")
    async with defense_fight(
        roles[0], ally_archetype=roles[1], library=((departing_index, "arcane_shield_spell"),)
    ) as fight:
        guest, host = fight.players[departing_index], fight.players[1 - departing_index]
        first, second = fight.enemies
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {"actor_id": first, **strike(guest, action=SWORD)},
                    {"actor_id": second, **strike(host, action=SWORD)},
                ]
            },
        )
        with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
            window = await open_stage(fight, stage)
            assert window["stage"] == stage and window["target_id"] == guest
            guest_before = await player_row(guest)
            host_before = await player_row(host)
            history = deepcopy((await fight.reload()).round_checkpoints)
            lifecycle = await depart(fight, guest)
            try:
                assert (await fight.reload()).round_checkpoints == history
                assert fight.sd.primary_player_id == host
                packets = []
                for _ in range(8):
                    receipt = await tool_receipt(fight, host, "resolve_phase", {})
                    assert not receipt.is_error, receipt.output
                    packets.extend(json.loads(receipt.output)["packets"])
                    state = await fight.reload()
                    if state.round_number == 2:
                        break
                else:
                    pytest.fail("The next round did not open")
                (cancelled,) = [packet for packet in packets if packet.get("outcome") == "target_left"]
                assert cancelled["actor_id"] == first
                assert cancelled["target_id"] == guest
                assert cancelled["resolved"] is False
                assert "left the fight" in cancelled["reason"]
                assert any(p["actor_id"] == second and p.get("damage", 0) > 0 for p in packets)
                assert (await player_row(host))["hp"]["current"] < host_before["hp"]["current"]
                guest_after = await player_row(guest)
                assert guest_after["hp"] == guest_before["hp"]
                assert guest_after.get("conditions") == guest_before.get("conditions")
                state = await fight.reload()
                assert_departed(state, guest)
                assert state.round_checkpoints[0] == history[-1]
            finally:
                await lifecycle.aclose()


async def test_declaration_departure_omits_guest(reset_db_pool) -> None:
    from db_mutations_conditions import save_player_conditions

    async with defense_fight("guardian") as fight:
        host, guest = fight.players
        history = deepcopy((await fight.reload()).round_checkpoints)
        await save_player_conditions(guest, [{"type": "poisoned", "source": "poison test fixture", "duration": None}])
        before = await player_row(guest)
        lifecycle = await depart(fight, guest)
        try:
            state = await fight.reload()
            assert state.round_checkpoints == history
            assert_departed(state, guest)
            refusal = await fight.command(
                "declare_phase",
                {"declarations": [{"actor_id": fight.enemies[0], **strike(guest, action=SWORD)}]},
                error=True,
            )
            assert "Unknown target" in refusal and guest in refusal
            await fight.command(
                "declare_phase",
                {"declarations": [{"actor_id": enemy, **strike(host, action=SWORD)} for enemy in fight.enemies]},
            )
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            assert all(packet["actor_id"] != guest and packet.get("target_id") != guest for packet in packets)
            assert any(packet.get("damage", 0) > 0 for packet in packets)
            state = await fight.reload()
            assert_departed(state, guest)
            for enemy in fight.enemies:
                foe = participant(state, enemy)
                foe.hp_current, foe.is_fallen = 0, True
            await fight.persist()
            await fight.command("end_combat", {"outcome": "victory"})
            after = await player_row(guest)
            assert after["hp"] == before["hp"]
            assert after["conditions"] == before["conditions"]
        finally:
            await lifecycle.aclose()


async def test_queued_declarations_drop_guest_turn_and_cancel_incoming_strike(reset_db_pool) -> None:
    from acceptance.test_martial_core_kit import weapon_attack

    async with defense_fight("warrior") as fight:
        host, guest = fight.players
        first, second = fight.enemies
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    weapon_attack(guest, first, ""),
                    {"actor_id": first, **strike(host, action=SWORD)},
                    {"actor_id": second, **strike(guest, action=SWORD)},
                ]
            },
        )
        before = participant(await fight.reload(), first).hp_current
        lifecycle = await depart(fight, guest)
        try:
            assert_departed(await fight.reload(), guest)
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            assert all(packet["actor_id"] != guest for packet in packets)
            assert any(p["actor_id"] == first and p.get("damage", 0) > 0 for p in packets)
            (cancelled,) = [p for p in packets if p.get("outcome") == "target_left"]
            assert (cancelled["actor_id"], cancelled["target_id"]) == (second, guest)
            state = await fight.reload()
            assert participant(state, first).hp_current == before
            assert_departed(state, guest)
        finally:
            await lifecycle.aclose()


async def test_multiattack_keeps_the_next_child_and_its_provenance(reset_db_pool) -> None:
    fight = MawlingHarness()
    try:
        await fight.start(reactions=True)
        host, guest = fight.players[:2]
        await fight.declare([guest, host])
        enemy = fight.enemies[0]
        await fight.command("resolve_phase", {})
        lifecycle = await depart(fight, guest)
        try:
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            (cancelled,) = [p for p in packets if p.get("outcome") == "target_left"]
            assert (cancelled["actor_id"], cancelled["target_id"]) == (enemy, guest)
            assert cancelled["strike_index"] == 0 and cancelled["execution_id"]
            (next_strike,) = [p for p in packets if p.get("strike_index") == 1]
            assert next_strike["composite"] == cancelled["composite"]
            assert next_strike["target_id"] == host and next_strike["damage"] > 0
        finally:
            await lifecycle.aclose()
    finally:
        await fight.close()


@pytest.mark.parametrize("leaver_role", ["patient", "marshal", "both"])
async def test_field_medic_declaration_survives_departure(reset_db_pool, leaver_role: str) -> None:
    from acceptance.test_valdris_party_yield import ability_action

    import ability_persistence
    import db_mutations
    import db_queries

    async with defense_fight("warrior", ally_archetype="marshal", extra_archetypes=("guardian",)) as fight:
        host, marshal, patient = fight.players
        foe = fight.enemies[0]
        if leaver_role == "both":
            patient = marshal
        leaver = patient if leaver_role == "patient" else marshal
        item_id = "healing_potion_minor"
        await db_mutations.add_inventory_item(host, item_id, 1, tainted=False)
        await ability_persistence.set_elective_equipped(marshal, "marshal_field_medic_order", equipped=True)
        await fight.command(
            "declare_phase",
            {"declarations": [ability_action(marshal, "marshal_field_medic_order", host)]},
        )
        await fight.drain()
        await fight.command(
            "declare_phase",
            {
                "declarations": [
                    {
                        "kind": "attack_consume",
                        "actor_id": host,
                        "action": "Longsword",
                        "target_id": foe,
                        "item_id": item_id,
                        "heal_target_id": patient,
                    }
                ],
            },
        )
        patient_before = (await player_row(patient))["hp"]
        enemy_before = participant(await fight.reload(), foe).hp_current
        lifecycle = await depart(fight, leaver)
        try:
            with patch.object(D20Roll, "roll", lambda self, _rng=None: self.evaluate(16)):
                packets = await fight.drain()
            final_hp = participant(await fight.reload(), foe).hp_current
            if leaver_role != "marshal":
                (cancelled,) = [p for p in packets if p.get("outcome") == "target_left"]
                assert (cancelled["actor_id"], cancelled["target_id"]) == (host, patient)
                assert final_hp == enemy_before
            else:
                assert final_hp < enemy_before
                assert all("field_medic" not in p for p in packets)
            assert (await player_row(patient))["hp"] == patient_before
            (potion,) = [p for p in await db_queries.get_player_inventory(host) if p["id"] == item_id]
            assert potion["slot_info"]["quantity"] == 1
        finally:
            await lifecycle.aclose()
