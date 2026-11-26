"""Targeting boundaries for concealed players and the actions that reveal them."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import move, strikes
from acceptance.mawling_harness import MawlingHarness
from acceptance.seeds import seed_known_spells
from acceptance.test_architect_fight import WORKS, pos
from acceptance.test_architect_fight import enter as enter_architect
from acceptance.test_architect_legendary import spend
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_self_buff_electives import bandit_attack, declare, enter_bandit_fight, equip, receipt
from acceptance.test_still_actions import reveal_and_wake
from acceptance.test_still_anchors import fresh_session
from acceptance.test_still_anchors import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_taunt import attack as taunt_attack
from acceptance.test_taunt import fight as fight
from acceptance.test_taunt import land_taunt
from acceptance.test_vanish import VANISH, refuse, vanish
from acceptance.test_vanish import walk as walk
from weapon_fixtures import DAGGER

import ability_persistence
import architect_actions
import combat_spatial
import db_queries
import reaction_spend
from spell_voice_rules import is_silenced

GIFT = "syrath_shadow_veil"


async def veil(walk: MawlingHarness) -> None:
    await walk.pool.execute(
        """UPDATE players SET data = data || '{"divine_favor":{"patron":"syrath","level":10,"max":100}}'
        WHERE player_id = $1""",
        walk.players[0],
    )
    result = await walk.command("activate", {"id": GIFT})
    assert result["concealment"]["concealed"] is True


async def test_taunt_releases_its_target_obligation(fight: MawlingHarness) -> None:
    warrior, ally = fight.players
    await land_taunt(fight)
    strike = taunt_attack(fight, ally)
    error = await fight.command("declare_phase", {"declarations": [strike]}, error=True)
    assert "Taunt" in error and warrior in error
    await veil(fight)
    await declare(fight, strike)
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        assert receipt(await fight.drain(), strike["actor_id"])["hit"] is False


async def test_shadow_veil_blocks_geometry_strike(walk: MawlingHarness) -> None:
    rogue, _ = walk.players
    walk.sd.location_id = WORKS
    state = await enter_architect(walk)
    assert state.architect_encounter is not None
    owner = state.architect_encounter["owner_id"]
    architect = state.get_participant(owner)
    assert architect is not None
    combat_spatial.place(state, rogue, pos(15, 5))
    await walk.persist()
    geometry = next(a for a in architect.action_pool if a["name"] == "Geometry Strike")
    assert architect_actions.geometry_auto_hit(state, owner, geometry, rogue, None)
    await veil(walk)
    strike = {**weapon_attack(owner, rogue, ""), "action": "Geometry Strike"}
    await refuse(walk, strike, rogue)
    before = await walk.snapshot()
    error = await spend(walk, owner, "Geometry Strike", target=rogue, error=True)
    assert "concealed" in error and rogue in error
    assert await walk.snapshot() == before


async def test_shadow_veil_blocks_serenitys_auto_hit(walk: MawlingHarness) -> None:
    rogue, _ = walk.players
    walk.sd.location_id = "ashmark_still"
    state = await reveal_and_wake(walk, count=2, action=DAGGER["name"])
    owner = state.still_encounter["owner_id"]
    combat_spatial.place(state, rogue, combat_spatial.position(state.spatial, owner))
    await walk.persist()
    await veil(walk)
    await refuse(walk, {**weapon_attack(owner, rogue, ""), "action": "Serenity's Touch"}, rogue)


async def test_shadow_veil_blocks_single_target_saves_but_not_choir_silence(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    opened = await walk.command("enter_mode", {"mode": "combat", "encounter_id": "hollow_choir"})
    search = next(a for a in opened["choir"]["search_actions"] if a["skill"] == "arcana")
    await declare(walk, {"actor_id": rogue, "kind": "interact", "action": search["action"]})
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        await walk.drain()
    state = await walk.reload()
    assert state.choir_encounter is not None
    owner = state.choir_encounter["owner_id"]
    choir = state.get_participant(owner)
    assert choir is not None and any(a["name"] == "Stolen Melody" for a in choir.action_pool)
    origin = combat_spatial.position(state.spatial, owner)
    for actor in (rogue, ally):
        combat_spatial.place(state, actor, {**origin, "x": origin["x"] + 10})
    await walk.persist()
    await veil(walk)
    melody = {
        "kind": "ability",
        "actor_id": owner,
        "action": "Stolen Melody",
        "targets": [rogue],
        "argument_type": "",
    }
    await refuse(walk, melody, rogue)
    silence = {**melody, "action": "Silence Void", "targets": [ally]}
    await declare(walk, silence)
    await walk.drain()
    state = await walk.reload()
    assert is_silenced(state, rogue) and is_silenced(state, ally)


async def test_concealed_move_preserves_enemy_reaction(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    foe = await enter_bandit_fight(walk)
    await veil(walk)
    state = await walk.reload()
    mover = state.get_participant(rogue)
    assert mover is not None
    mover.initiative = 30
    await walk.persist()
    await declare(walk, move(rogue, -15), move(ally, -15))
    with patch("check_resolution.dice_roll", return_value=_d20(1)) as rolls:
        packets = (await walk.command("resolve_phase", {}))["packets"]
    assert receipt(packets, rogue)["resolved"]
    assert strikes(packets)[0]["target_id"] == ally
    rolls.assert_called_once()
    state = await walk.reload()
    for actor in (rogue, ally):
        assert combat_spatial.position(state.spatial, actor) == pos(-15)
    assert reaction_spend.is_spent(state.reactions_available[foe])


@pytest.mark.parametrize("attack_kind", ["weapon", "spell", "departed_spell", "departed_weapon"])
async def test_vanished_attacker_becomes_targetable(walk: MawlingHarness, attack_kind: str) -> None:
    rogue, ally = walk.players
    await equip(walk, VANISH)
    await seed_known_spells(walk.pool, rogue, ("arcane_bolt",))
    foe = await enter_bandit_fight(walk)
    await declare(walk, vanish(rogue))
    await walk.drain()
    weapon = attack_kind.endswith("weapon")
    departed = attack_kind.startswith("departed")
    if weapon:
        attack = weapon_attack(rogue, foe, "", weapon=DAGGER["name"])
    else:
        attack = {"kind": "ability", "actor_id": rogue, "action": "arcane_bolt", "targets": [foe], "argument_type": ""}
    actions = [attack]
    if departed:
        state = await walk.reload()
        ally_actor = state.get_participant(ally)
        victim = state.get_participant(foe)
        assert ally_actor is not None and victim is not None
        ally_actor.initiative = 30
        victim.hp_current = 1
        await walk.persist()
        actions.append(weapon_attack(ally, foe, ""))
    await declare(walk, *actions)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15 if departed else 1)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = receipt(await walk.drain(), rogue)
    if departed:
        rolls.assert_called_once()
        refused = result if weapon else result["cast"]["damage_result"]
        assert refused["resolved"] is False
    reveal = result["concealment"] if weapon else result["cast"]["concealment"]
    assert reveal["ended_by"] == ("cast" if departed and not weapon else "attack")
    row = await db_queries.get_player(rogue)
    assert row is not None and row["flags"]["concealed"] is False
    if departed:
        foe = next(p.id for p in (await walk.reload()).participants if p.creature_id == "bandit" and not p.is_fallen)
    await declare(walk, await bandit_attack(walk, foe, rogue))


async def test_shadow_veil_cancels_a_strike_resumed_after_its_pre_roll_window(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    await walk.pool.execute(
        """UPDATE players SET data = data || '{"class":"cleric"}' WHERE player_id = $1""",
        ally,
    )
    foe = await enter_bandit_fight(walk)
    await declare(walk, await bandit_attack(walk, foe, rogue))
    with patch("check_resolution.dice_roll") as rolls:
        for _ in range(2):
            waiting = (await walk.command("resolve_phase", {}))["next"]["waiting_on"]
            if waiting:
                break
        assert waiting["stage"] == "pre_roll"
        assert any(r["actor_id"] == ally and r["id"] == "cleric_shield_of_faith" for r in waiting["reactions"])
        await veil(walk)
        await fresh_session(walk, await walk.reload())
        result = receipt(await walk.drain(), foe)
    rolls.assert_not_called()
    assert not result["resolved"] and "vanished" in result["reason"]


@pytest.mark.parametrize("hold", ["post_roll", "fate"])
async def test_shadow_veil_keeps_a_strike_whose_d20_is_committed(walk: MawlingHarness, hold: str) -> None:
    rogue = walk.players[0]
    if hold == "fate":
        await walk.pool.execute(
            """UPDATE players SET data = data || '{"divine_favor":{"patron":"zhael","level":40,"max":100}}'
            WHERE player_id = $1""",
            rogue,
        )
    foe = await enter_bandit_fight(walk)
    await declare(walk, await bandit_attack(walk, foe, rogue))
    with (
        patch("check_resolution.dice_roll", return_value=_d20(18)) as rolls,
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        for _ in range(3):
            paused = await walk.command("resolve_phase", {})
            if "fate_offer" in paused or (paused["next"]["waiting_on"] or {}).get("stage") == "post_roll":
                break
        if hold == "fate":
            assert paused["fate_offer"]["roller_id"] == foe
        else:
            waiting = paused["next"]["waiting_on"]
            assert any(r["actor_id"] == rogue and r["id"] == "rogue_uncanny_dodge" for r in waiting["reactions"])
        rolls.assert_called_once()
        # A live offer settles before any other tool runs; a reload drops it but keeps the held d20.
        await fresh_session(walk, await walk.reload())
        await veil(walk)
        await fresh_session(walk, await walk.reload())
        packets = await walk.drain()
    rolls.assert_called_once()
    result = receipt(packets, foe)
    assert result["resolved"] and result["hit"] and result["damage"] > 0
    row = await db_queries.get_player(rogue)
    assert row is not None and row["hp"]["current"] == 100 - result["damage"]


async def test_fireball_reaches_a_concealed_ally_in_its_area(walk: MawlingHarness) -> None:
    rogue, ally = walk.players
    await walk.pool.execute(
        """UPDATE players SET data = data || '{"class":"mage","focus":{"current":15,"max":15}}' WHERE player_id = $1""",
        ally,
    )
    await seed_known_spells(walk.pool, ally, ("arcane_fireball",))
    foe = await enter_bandit_fight(walk)
    state = await walk.reload()
    combat_spatial.place(state, ally, pos(-25))
    await walk.persist()
    await veil(walk)
    await refuse(walk, await bandit_attack(walk, foe, rogue), rogue)
    await declare(
        walk, {"kind": "ability", "actor_id": ally, "action": "arcane_fireball", "targets": [foe], "argument_type": ""}
    )
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("combat_spell_damage.dice.roll", return_value=_damage_die(24)),
    ):
        cast = receipt(await walk.drain(), ally)["cast"]
    damage = next(d for d in cast["damage_results"] if d["target_id"] == rogue)
    assert not damage["save"]["success"] and damage["damage"] > 0
    row = await db_queries.get_player(rogue)
    assert row is not None and row["hp"]["current"] == 100 - damage["damage"]


@pytest.mark.parametrize(
    ("equipped", "target", "error"),
    [(False, "self", "learned"), (True, "ally", "only the rogue"), (True, "self", "Stamina")],
)
async def test_vanish_refuses_invalid_targets_or_payment(
    walk: MawlingHarness, equipped: bool, target: str, error: str
) -> None:
    rogue, ally = walk.players
    if equipped:
        await equip(walk, VANISH)
    await ability_persistence.update_player_resources(rogue, stamina=4, conn=walk.pool)
    await enter_bandit_fight(walk)
    before = await walk.snapshot()
    action = {**vanish(rogue), "targets": [rogue if target == "self" else ally]}
    if target == "ally":
        refusal = await walk.command("declare_phase", {"declarations": [action]}, error=True)
    else:
        await declare(walk, action)
        refusal = await walk.command("resolve_phase", {}, error=True)
    assert error.casefold() in refusal.casefold()
    state, players = await walk.snapshot()
    assert players == before[1]
    assert state["beat"] == "declaration" and not state["pending_declarations"]
    if target == "ally":
        assert state == before[0]
