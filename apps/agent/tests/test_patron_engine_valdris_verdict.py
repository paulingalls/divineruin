from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from _mortaen_threshold_fixtures import active, declare, reload_state
from _patron_engine_fixtures import configure
from _thyra_wrath_fixtures import checkpoint, fighter, saved
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _valdris_verdict_fixtures import (
    FOE,
    GIFT,
    STRIKE,
    activate,
    advance,
    fight,
    omit_participant,
    queue_strike,
    refuse,
    set_health,
)
from _zhael_fate_fixtures import defend
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads
from voice_condition_fixtures import participant

import combat_fate
import combat_hold
import combat_phase
import db_mutations
import encounter_facts
import event_types as E
from combat_structures import add_wall
from conditions import apply_condition, has_condition
from patron_favor import _EXALTED_PERCENT
from patron_zero_hp import DAWNS_EMBRACE, DEATH_WARD
from zhael_fate import FATE, FateOffer


async def gift_info(call) -> dict:
    return next(g for g in (await call("query_info", kind="patron"))["abilities"] if g["id"] == GIFT)


async def assert_spent(world) -> None:
    assert (await row(world, 0))["patron_gifts"][GIFT] == {"spent": True}


async def assert_stunned_action(world, call, victim) -> None:
    hp = active(world).get_participant(victim).hp_current
    packets = await advance(world, call, "declaration")
    packet = next(p for p in packets if p["actor_id"] == FOE)
    assert packet["resolved"] is False and "stunned" in str(packet).lower()
    assert active(world).get_participant(victim).hp_current == hp
    assert not has_condition(active(world).get_participant(FOE).conditions, "stunned")


async def survivor(world, resistant: bool) -> None:
    foe = fighter(FOE, action_pool=[STRIKE.copy()], damage_affinities={"resistant": ["radiant"]} if resistant else {})
    async with fight(world, foe) as call:
        victim = world.ids[0]
        await queue_strike(world, call, victim)
        packets = await advance(world, call, "declaration")
        assert next(p for p in packets if p["actor_id"] == FOE)["hit"]
        assert encounter_facts.party_victims(active(world), FOE) == [victim]
        gift = await gift_info(call)
        await queue_strike(world, call, victim)
        result = await activate(call, notation="4d8")
        assert (gift["tier"], gift["status"], gift["state"], gift["recharge"], gift["available"]) == (
            "Exalted",
            "active",
            "ready",
            "per_session",
            True,
        )
        assert f'activate(id="{GIFT}", target_id=<living hostile creature id in this fight>)' in gift["activation_hint"]
        damage = 9 if resistant else 18
        name = active(world).get_participant(victim).name
        assert result["verdict"] == "unjust" and result["evidence"] == [{"id": victim, "name": name}]
        assert result["roll"] == {"notation": "4d8", "total": 18}
        assert result["damage"] == damage and result["stunned"]
        assert all(
            s in result["dm_cue"]
            for s in ("GOD_VALDRIS", "unjust", name, "4d8 rolled 18", f"{damage} radiant", "Stunned")
        )
        assert (await saved(world)).to_dict() == active(world).to_dict()
        assert active(world).get_participant(FOE).hp_current == 50 - damage
        await assert_spent(world)
        gift = await gift_info(call)
        assert (gift["state"], gift["available"], gift["spent"]) == ("spent", False, True)
        assert "new session" in gift["reason"]
        await refuse(world, call, "new session", target_id=FOE)
        await assert_stunned_action(world, call, victim)
        await queue_strike(world, call, victim)
        packets = await advance(world, call, "declaration")
        assert next(p for p in packets if p["actor_id"] == FOE)["hit"]


SCENARIOS = {GIFT: ("valdris_verdict:scales_verdict", survivor, [(False,), (True,)])}


@pytest.mark.parametrize("victim_kind", ["companion", "departed_guest"])
async def test_miss_is_unjust(world, victim_kind: str) -> None:
    async with fight(world) as call:
        victim_id = "companion" if victim_kind == "companion" else world.ids[1]
        victim = active(world).get_participant(victim_id)
        await queue_strike(world, call, victim.id)
        packets = await advance(world, call, "declaration", face=1)
        assert not next(p for p in packets if p["actor_id"] == FOE)["hit"]
        assert active(world).get_participant(victim.id).hp_current == victim.hp_current
        if victim_kind == "departed_guest":
            omit_participant(active(world), victim.id)
            await checkpoint(world)
            await reload_state(world)
        result = await activate(call, notation="4d8")
        assert result["verdict"] == "unjust" and result["evidence"] == [{"id": victim.id, "name": victim.name}]
        assert victim.name in result["dm_cue"]


@pytest.mark.parametrize("paused_wrap", [False, True])
async def test_late_verdict_stuns_next_resolution(world, paused_wrap: bool) -> None:
    async with fight(world) as call:
        victim = world.ids[0]
        await queue_strike(world, call, victim)
        await advance(world, call, "declaration")
        session = world.ctx.userdata
        if paused_wrap:
            await configure(world, "zhael", "warrior", index=1)
            actor = active(world).get_participant(victim)
            actor.conditions = apply_condition(actor.conditions, "frightened", source=FOE, duration=3)
            await checkpoint(world)
        await call("declare_phase", declarations=[defend(victim)])
        await advance(world, call, "narration")
        if paused_wrap:
            with patch("check_resolution.dice_roll", return_value=_d20(15)):
                held = await call("resolve_phase")
            assert held["fate_offer"]["roll_kind"] == "save"
            assert session.fate_offer is not None
            await reload_state(world)
            session.fate_offer = None
            await configure(world, "none", "warrior", index=1)
        assert bool(active(world).wrap_continuation) is paused_wrap
        assert not active(world).held_actions and active(world).ally_continuation is None
        result = await activate(call, notation="4d8")
        assert result["stunned"]
        await advance(world, call, "declaration")
        assert has_condition(active(world).get_participant(FOE).conditions, "stunned")
        with pytest.raises(ToolError, match="is stunned"):
            await queue_strike(world, call, victim)
        hp = active(world).get_participant(victim).hp_current
        await call("declare_phase", declarations=[defend(victim)])
        packets = await advance(world, call, "declaration")
        assert all(p["actor_id"] != FOE for p in packets)
        assert active(world).get_participant(victim).hp_current == hp
        assert not has_condition(active(world).get_participant(FOE).conditions, "stunned")
        await queue_strike(world, call, victim)
        packets = await advance(world, call, "declaration")
        assert next(p for p in packets if p["actor_id"] == FOE)["hit"]


async def test_just_verdict_consumes_temporary_hp_first(world) -> None:
    async with fight(world) as call:
        await set_health(world, 20, temp_hp=5)
        result = await activate(call)
        assert result["verdict"] == "just" and result["evidence"] == []
        assert result["roll"] == {"notation": "2d8", "total": 7}
        assert result["damage"] == 7 and not result["stunned"]
        assert "attacked no party member or companion" in result["dm_cue"]
        assert "5 temporary HP" in result["dm_cue"]
        player = await row(world, 0)
        assert player["hp"]["current"] == 18 and player["temp_hp"] == 0
        state = await saved(world)
        actor = participant(state, world.ids[0])
        assert (actor.hp_current, actor.temp_hp, participant(state, FOE).hp_current) == (18, 0, 50)
        await assert_spent(world)


@pytest.mark.parametrize("rescue", [False, True])
async def test_just_verdict_uses_normal_zero_hp_gifts(world, rescue: bool) -> None:
    async with fight(world) as call:
        actor, donor = world.ids
        await set_health(world, 4, gifts={DEATH_WARD: {"spent": False}})
        if rescue:
            await configure(
                world, "orenthel", "warrior", index=1, divine_favor={"patron": "orenthel", "level": 75, "max": 100}
            )
        result = await activate(call)
        state = await saved(world)
        assert state.to_dict() == active(world).to_dict()
        p = participant(state, actor)
        assert (p.hp_current, p.is_fallen, p.is_dead) == (10 if rescue else 0, not rescue, False)
        assert actor not in state.encounter_facts["ally_downers"]
        assert result["target_fallen"] is (not rescue)
        assert (await row(world, 0))["patron_gifts"][DEATH_WARD] == {"spent": False}
        await assert_spent(world)
        if rescue:
            assert (await row(world, 1))["patron_gifts"][DAWNS_EMBRACE] == {"spent": True}
            assert result["gift_owner"]["id"] == donor and result["gift_target"]["id"] == actor
            assert "Dawn's Embrace" in result["dm_cue"] and "10 HP" in result["dm_cue"]
        else:
            assert "gift_triggered" not in result and "falls" in result["dm_cue"]


@pytest.mark.parametrize("outcome", ["fall", "hollow_death", "victory"])
async def test_downed_foes_are_never_stunned(world, outcome) -> None:
    foes = [fighter(FOE, hp=5, xp_value=30, action_pool=[STRIKE.copy()])]
    if outcome == "fall":
        foes.append(fighter("survivor"))
    options = {"encounter": "hollow_wisp"} if outcome == "hollow_death" else {}
    async with fight(world, *foes, **options) as call:
        if outcome == "hollow_death":
            foe = active(world).get_participant("hollow_wisp_1")
            foe.hp_current = 5
            foe.action_pool = [STRIKE.copy()]
        else:
            foe = active(world).get_participant(FOE)
        await queue_strike(world, call, world.ids[0], foe.id)
        await advance(world, call, "declaration")
        state = active(world)
        xp_before = [(await row(world, i)).get("xp", 0) for i in range(2)]
        result = await activate(call, foe.id, notation="4d8")
        if outcome == "victory":
            agent, result = result
            assert agent is not None and result["outcome"] == "victory"
            assert result["xp_total"] == 30 and result["xp_granted"] > 0
            for i, before in enumerate(xp_before):
                assert (await row(world, i))["xp"] == before + result["xp_granted"]
            assert active(world) is None
            assert await db_mutations.load_combat_state(state.combat_id, conn=world.pool) is None
            events = published_payloads(world.ctx.userdata.room)
            assert [e["outcome"] for e in events if e["type"] == E.COMBAT_ENDED] == ["victory"]
        else:
            landed = participant(await saved(world), foe.id)
            assert (landed.hp_current, landed.is_fallen, landed.is_dead) == (0, True, outcome == "hollow_death")
            assert not has_condition(landed.conditions, "stunned")
        assert result["verdict"] == "unjust" and result["damage"] == (36 if outcome == "hollow_death" else 18)
        assert result["target_fallen"] and not result["stunned"]
        assert result["target_dead"] is (outcome == "hollow_death")
        assert ("dies" if outcome == "hollow_death" else "falls") in result["dm_cue"]
        await assert_spent(world)


@pytest.mark.parametrize(
    "options, reason",
    [
        ({"favor": _EXALTED_PERCENT - 1}, "Requires Exalted"),
        ({"patron": "mortaen"}, "follower of valdris"),
        ({"patron": "none"}, "Unbound"),
    ],
)
async def test_ineligible_follower_refused(world, options, reason) -> None:
    async with fight(world, **options) as call:
        await refuse(world, call, reason, target_id=FOE)


async def test_verdict_requires_combat(world) -> None:
    async with fight(world) as call:
        session = world.ctx.userdata
        state = session.combat_state
        session.combat_state = None
        try:
            await refuse(world, call, "only be used in combat", target_id=FOE)
            persisted = await db_mutations.load_combat_state(state.combat_id, conn=world.pool)
            assert persisted is not None and persisted.to_dict() == state.to_dict()
        finally:
            session.combat_state = state


@pytest.mark.parametrize(
    "selectors",
    [
        {},
        {"target_id": ""},
        {"target_ids": [FOE]},
        {"target_ids": [FOE, "wall"]},
        {"target_id": FOE, "target_ids": [FOE]},
        {"target_id": FOE, "condition": "poisoned"},
    ],
)
async def test_single_selector_required(world, selectors) -> None:
    async with fight(world) as call:
        await refuse(world, call, "Use target_id to select one", **selectors)


@pytest.mark.parametrize("target", ["unknown", "ally", "companion", "wall", "fallen", "dead", "zero"])
async def test_invalid_target_refused(world, target) -> None:
    extras = {
        "dead": fighter("dead", is_dead=True),
        "fallen": fighter("fallen", is_fallen=True),
        "zero": fighter("zero", hp=0),
    }
    async with fight(world, *extras.values(), fighter(FOE)) as call:
        if target == "wall":
            add_wall(active(world), "wall", "Slate Wall", {"x": 3, "y": -5, "z": 0}, {"x": 3, "y": 5, "z": 0})
            await checkpoint(world)
        await refuse(world, call, "living hostile creature", target_id=world.ids[1] if target == "ally" else target)


@pytest.mark.parametrize(
    "field,value",
    [("id", "different"), ("type", "companion"), ("hp_current", 0), ("is_fallen", True), ("is_dead", True)],
)
async def test_verdict_requires_living_acting_player(world, field, value) -> None:
    async with fight(world) as call:
        state = active(world)
        actor = state.get_participant(world.ids[0])
        if field == "id":
            omit_participant(state, actor.id)
        else:
            setattr(actor, field, value)
        await checkpoint(world)
        await refuse(world, call, "living acting player", target_id=FOE)


@pytest.mark.parametrize("field", ["ally_continuation", "held_actions"])
async def test_partial_round_refuses_verdict(world, field) -> None:
    async with fight(world) as call:
        await declare(world, call)
        state = active(world)
        if field == "ally_continuation":
            resolving, advance_result = combat_phase.advance_combat_phase(state)
            allies, hostiles = combat_phase.partition_packets(resolving, advance_result.packets)
            state.ally_continuation = combat_fate.begin_ally_pass(resolving, allies, hostiles, {})
        else:
            state.held_actions = combat_hold.hold_enemy_packets(state, [SimpleNamespace(actor_id=FOE, initiative=10)])
        assert bool(state.ally_continuation) is (field == "ally_continuation")
        assert bool(state.held_actions) is (field == "held_actions")
        await checkpoint(world)
        await refuse(world, call, "partially resolved", target_id=FOE)


async def test_live_fate_offer_refuses_verdict(world) -> None:
    async with fight(world) as call:
        session = world.ctx.userdata
        resume = AsyncMock()
        offer = FateOffer("wrap-save", "save", world.ids[0], 12, 12, {FATE: (world.ids[1],)}, Mock(), resume, Mock())
        session.fate_offer = offer
        await refuse(world, call, "partially resolved", target_id=FOE)
        assert session.fate_offer is offer
        resume.assert_not_called()


@pytest.mark.parametrize(
    "encounter, target_kind, reason",
    [
        ("hollow_still", "owner", "protected by the Still's anchors"),
        ("hollow_still", "anchor", "unrevealed Still anchor"),
        ("hollow_choir", "owner", "protected until its core is exposed"),
    ],
)
async def test_encounter_protections_refuse_verdict(world, encounter, target_kind, reason) -> None:
    async with fight(world, encounter=encounter) as call:
        state = active(world)
        record = state.still_encounter or state.choir_encounter
        target = record["owner_id"] if target_kind == "owner" else record["anchor_ids"][0]
        await refuse(world, call, reason, target_id=target)


@pytest.mark.parametrize("history", ["absent", "prior"])
async def test_legacy_checkpoint_refuses_verdict(world, history: str) -> None:
    async with fight(world) as call:
        state = active(world)
        data = state.to_dict()
        if history == "absent":
            del data["encounter_facts"]
        else:
            del data["encounter_facts"]["party_aggressors"]
        await db_mutations.save_combat_state(state.combat_id, data, conn=world.pool)
        await reload_state(world)
        await refuse(world, call, "aggression history is unknown", target_id=FOE)


@pytest.mark.parametrize("exposed", [False, True])
async def test_choir_protection_applies_only_to_unexposed_core(world, exposed: bool) -> None:
    async with fight(world, fighter(FOE), encounter="hollow_choir") as call:
        choir = active(world).choir_encounter
        if exposed:
            choir["phase"] = "exposed"
            await checkpoint(world)
        target = choir["owner_id"] if exposed else FOE
        result = await activate(call, target)
        assert result["verdict"] == "just" and result["judged_target"]["id"] == target
        await assert_spent(world)
