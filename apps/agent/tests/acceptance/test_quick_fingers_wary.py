"""Wary blocks new riders, then benefits one qualifying hostile attack."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.quick_fingers_harness import POCKET, FingersFight
from acceptance.quick_fingers_harness import fingers as fingers
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory

import combat_spatial
import db_mutations


async def reload_with_ally(fingers: FingersFight) -> None:
    ally_member = fingers.sd.member_state(fingers.players[1])
    await fresh_session(fingers, await fingers.reload())
    fingers.sd.party.members.append(ally_member)


@pytest.mark.parametrize("fingers", [{"players": 2}], indirect=True)
@pytest.mark.parametrize("concealed", [False, True])
async def test_wary_reload_retry_and_hostile_attack_order(fingers: FingersFight, concealed: bool):
    actor, ally = fingers.players
    enemy = await fingers.target()
    attack = enemy.action_pool[0]["name"]
    enemy.multiattack_sequence = {"name": "Multiattack", "attacks": [attack] * 3}
    state = fingers.sd.combat_state
    assert state is not None
    other = state.get_participant(fingers.enemies[1])
    assert other is not None
    other.initiative = enemy.initiative + 1
    spatial = combat_spatial.require_spatial(state)
    combat_spatial.place(state, other.id, combat_spatial.position(spatial, enemy.id))
    other_attack = weapon_attack(other.id, actor, "", weapon=other.action_pool[0]["name"])
    await fingers.persist()
    targets = [actor, ally, ally] if concealed else [ally, actor, actor]
    hostile = {
        "kind": "multiattack",
        "actor_id": enemy.id,
        "action": "Multiattack",
        "strikes": [{"action": attack, "target_id": target, "held_item_id": ""} for target in targets],
    }
    await fingers.declare(fingers.attack("steal"), fingers.attack("steal", actor=ally), hostile, other_attack)
    faces = [10, 17, 17]
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        patch("combat_quick_fingers.dice.roll") as selection,
    ):
        first = await fingers.command("resolve_phase", {})
    assert d20.call_count == len(faces)
    selection.assert_not_called()
    receipts = {p["actor_id"]: p for p in first["packets"] if "quick_fingers" in p}
    failed = receipts[actor]["quick_fingers"]
    assert failed["total"] < failed["dc"] and not failed["success"] and failed["wary"]
    blocked = receipts[ally]["quick_fingers"]
    assert blocked["total"] is None and not blocked["success"] and blocked["wary"]
    assert all(receipts[pid]["roll"] == 17 for pid in (actor, ally))
    assert (await fingers.target()).carried_items == POCKET
    assert await fingers.resources() == (8, 10)
    assert (
        await fingers.pool.fetchval("SELECT data->'stamina'->>'current' FROM players WHERE player_id=$1", ally) == "8"
    )

    saved = await fingers.reload()
    assert saved.quick_fingers_wary == {enemy.id: {actor: {"round": 1, "attack_pending": True}}}
    assert saved.held_actions
    if concealed:
        await db_mutations.set_player_flag(actor, "concealed", True)
    await reload_with_ally(fingers)

    faces = [13, 16] if concealed else [5, 3, 13, 19, 16]
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(face) for face in faces]) as d20,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
    ):
        packets = []
        for _ in range(6):
            result = await fingers.command("resolve_phase", {})
            packets.extend(result["packets"])
            state = await fingers.reload()
            head = state.held_actions[0] if state.held_actions else None
            if head and head.get("strike_index") == 1 and head["roll"] is not None:
                assert state.quick_fingers_wary[enemy.id][actor]["attack_pending"] is concealed
                await reload_with_ally(fingers)
                break
        else:
            pytest.fail("The second strike never held a committed roll")
        packets.extend(await fingers.drain())
    assert d20.call_count == len(faces)
    strikes = [p for p in packets if p.get("actor_id") == enemy.id and "strike_index" in p]
    assert [p["strike_index"] for p in strikes] == [0, 1, 2]
    other_strike = next(p for p in packets if p.get("actor_id") == other.id and "resolved" in p)
    if concealed:
        assert other_strike["resolved"] is False and "concealed" in other_strike["reason"]
        assert strikes[0]["resolved"] is False and "concealed" in strikes[0]["reason"]
        assert [p["roll"] for p in strikes[1:]] == [13, 16]
        await db_mutations.set_player_flag(actor, "concealed", False)
    else:
        assert other_strike["roll"] == 5
        assert [p["roll"] for p in strikes] == [3, 19, 16]
        assert [p["attack_total"] - p["roll"] for p in strikes] == [enemy.action_pool[0]["to_hit"]] * 3

    state = await fingers.reload()
    assert state.round_number == 2 and state.quick_fingers_wary == {}
    assert state.round_checkpoints[-1]["combat"]["quick_fingers_wary"] == {}
    await fingers.declare({**weapon_attack(enemy.id, actor, ""), "action": attack})
    with patch("check_resolution.dice_roll", return_value=_d20(2)) as d20:
        next_round = await fingers.drain()
    d20.assert_called_once()
    assert any(packet.get("roll") == 2 for packet in next_round)
