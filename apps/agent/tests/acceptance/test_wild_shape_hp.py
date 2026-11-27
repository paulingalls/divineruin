"""Damage to a Wild Shape through registered encounter tools."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._wild_shape_hp_helpers import (
    damage_roll,
    declare_hit,
    declare_round,
    events,
    land,
    patch_player,
    saved_pools,
    set_temp,
)
from acceptance._wild_shape_hp_helpers import fight as fight
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_bark_skin import keep_original, spend
from acceptance.test_guardian_intercept import INTERCEPT, opening, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import strike
from acceptance.test_wild_shape import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_wild_shape import updates
from livekit.agents.llm import ToolError

import db_mutations
import db_mutations_concentration
import db_queries
import event_types
from declarations import DEFEND_AC_BONUS


@pytest.mark.parametrize("fight", ["phase", "immediate"], indirect=True)
async def test_hit_consumes_beast_hp(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = await land(fight, monkeypatch, 7)
    assert receipt["damage"] == 7
    assert await saved_pools(fight) == (30, 0, 4)
    assert (receipt["beast_hp_absorbed"], receipt["beast_hp_remaining"]) == (7, 4)
    assert "wild_shape_ended" not in receipt
    assert any(
        row["wildShape"]["hpCurrent"] == 4
        for event in updates(fight)
        for row in event["combatants"]
        if row["id"] == fight.players[0] and "wildShape" in row
    )


@pytest.mark.parametrize("damage", [4, 10])
async def test_depletion_restores_own_shape(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch, damage: int
) -> None:
    pid = fight.players[0]
    shape = participant(await fight.reload(), pid).wild_shape
    assert shape is not None
    shape["hp_current"] = 4
    await fight.persist()
    receipt = await land(fight, monkeypatch, damage)
    carryover = damage - 4
    assert receipt["damage"] == damage
    assert await saved_pools(fight) == (30 - carryover, 0, None)
    actor = participant(await fight.reload(), pid)
    assert (actor.ac, actor.action_pool, actor.deferred_effects) == (
        shape["original_ac"],
        shape["original_action_pool"],
        shape["original_deferred_effects"],
    )
    ended = [{"actor_id": pid, "form_id": "grey_wolf", "reason": "beast_hp_depleted", "carryover_damage": carryover}]
    assert receipt["wild_shape_ended"] == ended
    assert "form" in receipt["dm_cue"] and str(carryover) in receipt["dm_cue"]
    (update,) = [event for event in updates(fight) if event.get("wild_shape_ended") == ended]
    assert "wildShape" not in next(row for row in update["combatants"] if row["id"] == pid)
    if carryover:
        await land(fight, monkeypatch, 7)
        assert await saved_pools(fight) == (17, 0, None)


@pytest.mark.parametrize("fight", ["phase:thyra"], indirect=True)
async def test_thyra_temp_hp_precedes_beast_hp(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    assert await saved_pools(fight) == (30, 5, 11)
    receipt = await land(fight, monkeypatch, 8)
    assert await saved_pools(fight) == (30, 0, 8)
    assert (receipt["temp_hp_absorbed"], receipt["beast_hp_absorbed"]) == (5, 3)


async def test_resisted_hit_lands_after_affinity(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = fight.players[0]
    participant(await fight.reload(), pid).damage_affinities = {"resistant": ["piercing"]}
    await fight.persist()
    await set_temp(fight, pid, 1)
    receipt = await land(fight, monkeypatch, 8)
    assert await saved_pools(fight) == (30, 0, 8)
    assert (receipt["damage"], receipt["temp_hp_absorbed"], receipt["beast_hp_absorbed"]) == (4, 1, 3)


@pytest.mark.parametrize("fight", ["phase:spell"], indirect=True)
async def test_spell_save_for_half_lands_on_beast(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, caster = fight.players
    shape = participant(await fight.reload(), pid).wild_shape
    assert shape is not None
    shape["hp_current"] = 3
    await fight.persist()
    await set_temp(fight, pid, 1)
    await declare_round(
        fight,
        {
            "kind": "ability",
            "actor_id": caster,
            "action": "arcane_fireball",
            "targets": [pid],
            "argument_type": "",
            "reshape": [],
        },
    )
    monkeypatch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(19))
    monkeypatch.setattr("combat_spell_damage.dice.roll", lambda *_, **__: _damage_die(8))
    cast = next(p["cast"] for p in await fight.drain() if p.get("cast"))
    hit = next(d for d in cast["damage_results"] if d["target_id"] == pid)
    assert hit["save"]["success"] and hit["save"]["half_on_success"]
    assert await saved_pools(fight) == (30, 0, None)
    (event,) = [event for event in updates(fight) if event.get("wild_shape_ended") == hit["wild_shape_ended"]]
    assert "wildShape" not in next(row for row in event["combatants"] if row["id"] == pid)
    assert (hit["damage"], hit["temp_hp_absorbed"], hit["beast_hp_absorbed"]) == (4, 1, 3)


@pytest.mark.parametrize("fight", ["phase:mawling"], indirect=True)
async def test_turn_start_field_depletes_beast(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = fight.players[0]
    await declare_hit(fight, "Lunge")
    damage_roll(monkeypatch, 8)
    await fight.drain()
    actor = participant(await fight.reload(), pid)
    assert any(c["type"] == "grappled" and c["source"] == "bandit_1" for c in actor.conditions)
    await set_temp(fight, pid, 1)
    await declare_round(fight)
    monkeypatch.setattr("combat_turn_start.dice_roll", lambda *_, **__: _damage_die(5))
    packet = next(p for p in await fight.drain() if p.get("automatic") and p["target_id"] == pid)
    assert await saved_pools(fight) == (29, 0, None)
    assert (packet["damage"], packet["temp_hp_absorbed"], packet["beast_hp_absorbed"]) == (5, 1, 3)
    assert any(update.get("wild_shape_ended") == packet["wild_shape_ended"] for update in updates(fight))


@pytest.mark.parametrize(
    ("fight", "hold_save"), [("phase:intercept", True), ("immediate:intercept", False)], indirect=["fight"]
)
async def test_guardian_intercepts_away_from_beast(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch, hold_save: bool
) -> None:
    pid, guardian = fight.players
    state = await fight.reload()
    participant(state, pid).hp_current = 4
    participant(state, guardian).damage_affinities = {"resistant": ["piercing"]}
    await fight.persist()
    await set_temp(fight, guardian, 2)
    await set_temp(fight, pid, 1)
    spell = "divine_bless"
    await db_mutations_concentration.update_player_concentration(guardian, spell, conn=fight.pool)
    fight.sd.member_state(guardian).concentration.spell_id = spell
    await declare_hit(fight)
    damage_roll(monkeypatch, 10)
    window = await opening(fight)
    assert any(r["id"] == INTERCEPT for r in window["reactions"])
    assert await saved_pools(fight) == (4, 1, 11)
    roll = next(packet for packet in reversed(events(fight)) if packet["type"] == event_types.DICE_ROLL)
    assert roll["context"] != "killing_blow"
    reaction = await tool_receipt(fight, guardian, "activate", {"id": INTERCEPT})
    assert not reaction.is_error, reaction.output
    monkeypatch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(4))
    if hold_save:
        result = await fight.command("resolve_phase", {})
        assert await saved_pools(fight) == (4, 1, 11)
        paused = result["fate_offer"]
        assert (paused["roll_kind"], paused["roller_id"]) == ("save", guardian)
        state = await fight.reload()
        assert (participant(state, guardian).hp_current, participant(state, guardian).temp_hp) == (97, 0)
        packets = (await keep_original(fight, paused))["packets"]
    else:
        packets = await fight.drain()
    assert await saved_pools(fight) == (4, 1, 11)
    receipt = next(p for p in packets if p.get("hit"))
    assert receipt["concentration_broken"] == spell
    actor = participant(await fight.reload(), guardian)
    row = await db_queries.get_player(guardian)
    assert row is not None
    assert (actor.hp_current, actor.temp_hp) == (row["hp"]["current"], row["temp_hp"]) == (97, 0)
    assert (receipt["target_id"], receipt["damage_target_id"], receipt["damage"]) == (pid, guardian, 5)


@pytest.mark.parametrize("fight", ["phase:bear", "immediate:wolf"], indirect=True)
async def test_concentration_uses_landed_amount(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    await patch_player(fight, pid, attributes={**actor.attributes, "constitution": 10})
    assert actor.wild_shape is not None
    bear = actor.wild_shape["form_id"] == "dire_bear"
    if not bear:
        actor.wild_shape["hp_current"] = 4
    await fight.persist()
    spell = "divine_bless"
    await db_mutations_concentration.update_player_concentration(pid, spell, conn=fight.pool)
    fight.sd.concentration.spell_id = spell
    await declare_hit(fight)
    damage_roll(monkeypatch, 30, face=14)
    expected = (30, 0, 30) if bear else (4, 0, None)
    packets = []
    if bear:
        round_number = (await fight.reload()).round_number
        for _ in range(6):
            result = await fight.command("resolve_phase", {})
            if offer := result.get("fate_offer"):
                if offer["roll_kind"] == "save":
                    assert (offer["roller_id"], offer["total"]) == (pid, 14)
                    assert await saved_pools(fight) == expected
                    break
                packets += (await keep_original(fight, offer))["packets"]
        else:
            assert await saved_pools(fight) == expected
            assert await db_mutations_concentration.read_player_concentration(pid) == {"spell_id": None}
            raise AssertionError("Concentration did not pause")
        packets += (await keep_original(fight, offer))["packets"]
        if (await fight.reload()).round_number == round_number:
            packets += await fight.drain()
    else:
        packets = await fight.drain()
    receipt = next(p for p in packets if p.get("hit"))
    assert await saved_pools(fight) == expected
    assert await db_mutations_concentration.read_player_concentration(pid) == {"spell_id": None}
    assert fight.sd.concentration.spell_id is None
    assert receipt["concentration_broken"] == spell


@pytest.mark.parametrize(("own", "damage", "dead"), [(6, 10, False), (30, 63, False), (30, 64, True)])
async def test_own_hp_controls_death(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch, own: int, damage: int, dead: bool
) -> None:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    assert actor.wild_shape is not None
    actor.wild_shape["hp_current"] = 4
    actor.hp_current = own
    await fight.persist()
    await land(fight, monkeypatch, damage)
    actor = participant(await fight.reload(), pid)
    assert actor.is_dead is dead
    assert await saved_pools(fight) == (0, 0, None)
    if not dead:
        assert actor.is_fallen
        monkeypatch.setattr("combat_resolution.dice_roll", lambda *_, **__: _d20(14))
        receipt = await fight.command("request_death_save", {"player_id": pid})
        assert receipt["success"] and receipt["total_successes"] == 1
        assert participant(await fight.reload(), pid).death_save_successes == 1


@pytest.mark.parametrize("fight", ["phase:drain"], indirect=True)
async def test_drain_counts_damage_to_beast(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    attacker = participant(await fight.reload(), "bandit_1")
    attacker.hp_current = 40
    await fight.persist()
    await declare_hit(fight, "Absorb")
    damage_roll(monkeypatch, 7)
    receipt = next(p for p in await fight.drain() if p.get("hit"))
    assert await saved_pools(fight) == (30, 0, 4)
    assert participant(await fight.reload(), "bandit_1").hp_current == 47
    assert (receipt["self_healed"], receipt["temp_hp_absorbed"], receipt["beast_hp_absorbed"]) == (7, 0, 7)


@pytest.mark.parametrize(
    ("fight", "verb"), [("phase", "resolve_phase"), ("phase:inner_fire", "activate")], indirect=["fight"]
)
async def test_failed_landing_rolls_back_pools_and_events(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    assert actor.wild_shape is not None
    actor.wild_shape["hp_current"] = 4
    await fight.persist()
    if verb == "activate":
        args = {"id": "draethar_inner_fire"}
        monkeypatch.setattr("draethar_inner_fire.dice.roll", lambda *_, **__: _damage_die(10))
    else:
        args = {}
        await declare_hit(fight)
        damage_roll(monkeypatch, 10)
        await opening(fight)
    before = await fight.snapshot()
    published = events(fight)
    concentration = deepcopy(fight.sd.concentration)
    original = db_mutations.save_combat_state

    async def fail_after_write(combat_id, data, *, conn=None):
        await original(combat_id, data, conn=conn)
        written = await db_mutations.load_combat_state(combat_id, conn=conn)
        row = await db_queries.get_player(pid, conn=conn)
        assert written is not None and row is not None
        saved = participant(written, pid)
        assert (saved.wild_shape, saved.hp_current, row["hp"]["current"]) == (None, 24, 24)
        raise ToolError("Injected after both HP writes")

    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_write)
        error = await fight.command(verb, args, error=True)
        assert "Injected after both HP writes" in error
    assert await fight.snapshot() == before
    assert events(fight) == published and fight.sd.concentration == concentration
    if verb == "activate":
        receipt = await fight.command(verb, args)
    else:
        receipt = next(p for p in await fight.drain() if p.get("hit"))
    assert await saved_pools(fight) == (24, 0, None)
    assert "form dropped" in receipt["dm_cue"]
    assert any(event.get("wild_shape_ended") == receipt["wild_shape_ended"] for event in updates(fight))


@pytest.mark.parametrize("fight", ["phase:verdict"], indirect=True)
async def test_just_verdict_keeps_form_drop_cue(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    assert actor.wild_shape is not None
    actor.wild_shape["hp_current"] = 4
    await fight.persist()
    monkeypatch.setattr("valdris_verdict.dice.roll", lambda notation: SimpleNamespace(total=7, notation=notation))
    receipt = await fight.command("activate", {"id": "valdris_the_scales_verdict", "target_id": "bandit_1"})
    assert receipt["verdict"] == "just"
    assert await saved_pools(fight) == (27, 0, None)
    assert "form dropped" in receipt["dm_cue"]
    assert any(event.get("wild_shape_ended") == receipt["wild_shape_ended"] for event in updates(fight))


@pytest.mark.parametrize("fight", ["phase:drain"], indirect=True)
async def test_incorporeal_floor_applies_to_own_hp(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    actor = participant(await fight.reload(), fight.players[0])
    actor.conditions.append({"type": "incorporeal", "duration": 2, "source": "threshold_walk", "stacks": 1})
    await fight.persist()
    await declare_hit(fight, "Absorb")
    damage_roll(monkeypatch, 50)
    receipt = next(p for p in await fight.drain() if p.get("hit"))
    assert receipt["carryover_damage"] == 39
    assert await saved_pools(fight) == (1, 0, None)
    assert not participant(await fight.reload(), fight.players[0]).is_fallen


async def test_bark_skin_survives_own_ac_restoration(fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = fight.players[0]
    state = await fight.reload()
    actor = participant(state, pid)
    assert actor.wild_shape is not None
    own_ac = actor.wild_shape["original_ac"]
    actor.wild_shape["hp_current"] = 4
    attackers = ("bandit_1", "bandit_2", "bandit_3")
    for initiative, enemy in enumerate(reversed(attackers), start=30):
        participant(state, enemy).initiative = initiative
    state.initiative_order = [*attackers, *(p for p in state.initiative_order if p not in attackers)]
    await fight.persist()
    await declare_round(fight, *(strike(enemy, pid, "Light Crossbow") for enemy in attackers))
    base = 12 + DEFEND_AC_BONUS
    modifier = next(a["to_hit"] for a in participant(state, attackers[0]).action_pool if a["name"] == "Light Crossbow")
    modifier += participant(state, attackers[0]).attack_mod
    faces = iter((base + 1 - modifier, 18, 18))
    monkeypatch.setattr("check_resolution.dice_roll", lambda *_, **__: _d20(next(faces)))
    monkeypatch.setattr("check_resolution_attack.dice_roll", lambda *_, **__: _damage_die(6))
    await spend(fight, await opening(fight), "druid")
    packets = {p["actor_id"]: p for p in await fight.drain() if "hit" in p}
    assert (packets["bandit_1"]["target_ac"], packets["bandit_1"]["damage"]) == (base + 2, 0)
    assert packets["bandit_2"]["target_ac"] == base + 2 and packets["bandit_2"]["wild_shape_ended"]
    assert packets["bandit_3"]["target_ac"] == own_ac + DEFEND_AC_BONUS + 2
    assert await saved_pools(fight) == (26, 0, None)
    actor = participant(await fight.reload(), pid)
    assert actor.ac == own_ac and not actor.bark_skin_active


async def test_bark_skin_hit_that_still_lands_takes_beast_hp_first(
    fight: MawlingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = fight.players[0]
    actor = participant(await fight.reload(), pid)
    assert actor.wild_shape is not None
    await patch_player(fight, pid, hp={"current": 5, "max": 30})
    actor.hp_current = 5
    await fight.persist()
    await declare_hit(fight)
    damage_roll(monkeypatch, 7, face=18)
    for _ in range(4):
        window = (await fight.command("resolve_phase", {}))["next"]["waiting_on"]
        if window and any(r["id"] == "druid_bark_skin" for r in window["reactions"]):
            break
    else:
        raise AssertionError("the held hit never offered Bark Skin")
    await spend(fight, window, "druid")
    receipt = next(p for p in await fight.drain() if p.get("hit"))
    assert (receipt["damage"], receipt["beast_hp_absorbed"], receipt["beast_hp_remaining"]) == (7, 7, 4)
    # 7 damage would fell a 5 HP druid if the landing skipped the beast pool.
    assert (receipt["context"], receipt["dramatic"], receipt["target_fallen"]) == ("", False, False)
    assert await saved_pools(fight) == (5, 0, 4)
