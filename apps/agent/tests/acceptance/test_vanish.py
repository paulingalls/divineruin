"""Persisted concealment through registered combat tools."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import (
    bandit_attack,
    declare,
    defend,
    discovered,
    enter_bandit_fight,
    equip,
    receipt,
)
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from weapon_fixtures import DAGGER

import ability_persistence
import combat_spatial
import db_mutations
import db_queries
import mentor_variant_progress
from activate_tools import activate
from combat_enemy_action import is_combined_attack_action

VANISH = "rogue_vanish"


@pytest.fixture
async def walk(reset_db_pool: str):
    harness = MawlingHarness()
    try:
        await harness.prepare((8, 8), companion=None, tools=(activate,))
        await harness.pool.execute(
            "UPDATE players SET data = data || jsonb_build_object('class', 'rogue', 'equipment', "
            "jsonb_build_object('main_hand', $2::jsonb)) WHERE player_id = $1",
            harness.players[0],
            json.dumps(DAGGER),
        )
        harness.encounter_id = "bandit_ambush"
        yield harness
    finally:
        await harness.close()


def vanish(actor: str) -> dict:
    return {"kind": "ability", "actor_id": actor, "action": VANISH, "targets": [], "argument_type": "", "reshape": []}


async def refuse(walk: MawlingHarness, strike: dict, target: str) -> None:
    before = await walk.snapshot()
    error = await walk.command("declare_phase", {"declarations": [strike]}, error=True)
    assert "concealed" in error and target in error
    assert await walk.snapshot() == before


async def test_hide_blocks_targeting_and_allows_redeclaration(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    foe = await enter_bandit_fight(walk)
    await declare(walk, weapon_attack(rogue, foe, "hide", weapon=DAGGER["name"]))
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(20)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await walk.drain()
    await refuse(walk, await bandit_attack(walk, foe, rogue), rogue)
    await declare(walk, await bandit_attack(walk, foe, ally))
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        assert receipt(await walk.drain(), foe)["hit"] is False


async def test_vanish_wastes_queued_attack_and_survives_reload(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    await walk.pool.execute("""UPDATE players SET data = data || '{"class":"cleric"}' WHERE player_id = $1""", ally)
    await equip(walk, VANISH)
    foe = await enter_bandit_fight(walk)
    await discovered(walk, VANISH)
    strike = await bandit_attack(walk, foe, rogue)
    before = await db_queries.get_player(rogue)
    assert before is not None
    await declare(walk, vanish(rogue), strike)
    with patch("check_resolution.dice_roll") as rolls:
        ally_band = await walk.command("resolve_phase", {})
        result = receipt(ally_band["packets"], rogue)
        assert result["concealment"]["concealed"] is True
        after = await db_queries.get_player(rogue)
        assert after is not None and after["flags"]["concealed"] is True
        assert after["stamina"]["current"] == before["stamina"]["current"] - 5
        assert after["focus"] == before["focus"]
        await fresh_session(walk, await walk.reload())
        enemy_band = await walk.command("resolve_phase", {})
        assert enemy_band["next"]["waiting_on"] is None
        result = receipt(enemy_band["packets"], foe)
        assert result["resolved"] is False and "vanished" in result["reason"]
    rolls.assert_not_called()
    if (await walk.reload()).beat != "declaration":
        await walk.drain()
    final = await db_queries.get_player(rogue)
    assert final is not None and final["hp"] == before["hp"]
    await refuse(walk, strike, rogue)
    variant = "rogue_vanish_tidecaller"
    await mentor_variant_progress.record_unlocked(rogue, variant, conn=walk.pool)
    await ability_persistence.set_active_variant(rogue, VANISH, variant, conn=walk.pool)
    await declare(walk, {**vanish(rogue), "action": variant, "targets": [rogue]}, defend(foe))
    result = receipt(await walk.drain(), rogue)
    assert result["concealment"]["before"] is True
    assert result["variant_id"] == variant and result["deducted"] == {"stamina": 4, "focus": 0}


async def test_vanish_ends_with_the_encounter(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    await db_mutations.set_player_flag(ally, "concealed", True, conn=walk.pool)
    await equip(walk, VANISH)
    foe = await enter_bandit_fight(walk)
    await declare(walk, vanish(rogue), defend(foe))
    assert receipt(await walk.drain(), rogue)["concealment"]["concealed"] is True

    await walk.command("end_combat", {"outcome": "fled"})
    party = walk.sd.party
    await fresh_session(walk)
    walk.sd.party = party
    foe = await enter_bandit_fight(walk)
    await refuse(walk, await bandit_attack(walk, foe, ally), ally)
    await declare(walk, await bandit_attack(walk, foe, rogue))


@pytest.mark.parametrize("kind", ["combined", "multiattack"])
async def test_vanish_cancels_only_the_targeted_strike(walk: MawlingHarness, kind: str) -> None:
    rogue, ally = walk.players
    await equip(walk, VANISH)
    walk.encounter_id = "hollow_corrupted_settlement"
    walk.roster = (await walk.command("enter_mode", {"mode": "combat", "encounter_id": walk.encounter_id}))[
        "participants"
    ]
    walk.enemies = [p["id"] for p in walk.roster if p["type"] == "enemy"]
    state = await walk.reload()
    hunter = next(p for p in state.participants if p.id == walk.enemies[0])
    origin = combat_spatial.position(combat_spatial.require_spatial(state), rogue)
    for actor in (hunter.id, ally):
        combat_spatial.place(state, actor, origin)
    await walk.persist()
    if kind == "multiattack":
        strike = walk.composite([ally, rogue])
    else:
        action = next(a for a in hunter.action_pool if is_combined_attack_action(a))
        strike = {**weapon_attack(hunter.id, rogue, ""), "action": action["name"]}
    await declare(walk, vanish(rogue), strike)
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        packets = [p for p in await walk.drain() if p["actor_id"] == hunter.id]
    assert packets[-1]["resolved"] is False and "vanished" in packets[-1]["reason"]
    if kind == "multiattack":
        assert packets[0]["target_id"] == ally and packets[0]["hit"] is False
        assert rolls.call_count == 1
    else:
        rolls.assert_not_called()
    await refuse(walk, strike, rogue)
