from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from itertools import chain, repeat
from unittest.mock import MagicMock, patch

import pytest
from acceptance import defensive_reactions_harness as defense
from acceptance._capstone_helpers import _damage_die
from acceptance.counter_reactions_harness import WEAPON
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import BANDIT, SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_self_buff_electives import declare
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_spell_reaction_offers import FAITH, resources
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

from check_resolution import D20CheckCore, D20Roll
from combat_participant import CombatParticipant
from combat_spatial import require_spatial
from combat_structures import THORNWALL, add_wall

BARK, LOOK = "warden_bark_skin", "lookout"
pytestmark = pytest.mark.usefixtures("reset_db_pool")


@asynccontextmanager
async def faith_fight(
    *totals: int | None, fate: bool = False, skirmisher: bool = False
) -> AsyncIterator[MawlingHarness]:
    rolls = chain(totals, repeat(totals[-1]))

    def roll(d20: D20Roll, _rng=None) -> D20CheckCore:
        total = next(rolls)
        return d20.evaluate(20 if total is None else total - d20.modifier)

    archetype, gear = ("skirmisher", WEAPON) if skirmisher else ("warden", None)
    async with defense.defense_fight(
        archetype,
        fate=fate,
        gear=gear,
        ally_archetype="diplomat",
        extra_archetypes=("marshal",),
        library=((1, FAITH), (2, FAITH)),
    ) as fight:
        _, caster, guest = fight.players
        state = await fight.reload()
        participant(state, caster).ac = participant(state, guest).ac = 16
        require_spatial(state)["positions"][caster] = pos(25)
        await fight.persist()
        damage = patch("check_resolution_attack.dice_roll", return_value=_damage_die(7))
        with patch.object(D20Roll, "roll", roll), damage:
            yield fight


async def cast(fight: MawlingHarness, actor: str, ability: str = FAITH, *, already_open: bool = False) -> list[dict]:
    focus, resonance = await resources(fight, actor)
    if not already_open:
        packets = await defense.spend(fight, ability, stage="post_roll", actor=actor, cost=2)
    else:
        receipt = await tool_receipt(fight, actor, "activate", {"id": ability})
        assert not receipt.is_error, receipt.output
        packets = []
    await defense.reload_session(fight)
    assert await resources(fight, actor) == (focus - 2, resonance + (ability == FAITH))
    return packets


async def refuse(fight: MawlingHarness, actor: str, window: dict | None, *, already_offered: bool = False) -> None:
    before = await resources(fight, actor)
    receipt = await tool_receipt(fight, actor, "activate", {"id": FAITH})
    assert receipt.is_error and await resources(fight, actor) == before, receipt.output
    assert not (await fight.reload()).reactions_available.get(actor, {}).get("spent")
    offers = {(r["actor_id"], r["id"]) for r in window["reactions"]} if window else set()
    assert ((actor, FAITH) in offers) == already_offered, window
    assert not already_offered or "already warded" in receipt.output


def sources(target: CombatParticipant) -> list[str]:
    return [c["originating_participant_id"] for c in target.conditions if c["type"] == "shield_of_faith"]


def assert_attack(packets: list[dict], actor: str, ac: int, hit: bool, damage: int | None = None) -> dict:
    attacks = [p for p in packets if p["actor_id"] == actor and "hit" in p]
    assert len(attacks) == 1, packets
    (packet,) = attacks
    assert packet["resolved"] and (packet["target_ac"], packet["hit"]) == (ac, hit), packet
    assert packet["damage"] == (damage if damage is not None else 7 * hit), packet
    return packet


async def assert_faith(
    fight: MawlingHarness, packets: list[dict], caster: str, ally: str, *, departed: bool = False
) -> CombatParticipant:
    receipts = [p for p in packets if p.get("ability_id") == FAITH and p["actor_id"] == caster]
    assert [(p.get("target_id"), p.get("ac_bonus")) for p in receipts] == [(ally, 2)], packets
    saved = participant(await fight.reload(), ally)
    assert sources(saved) == ([] if departed else [caster])
    return saved


async def depart(fight: MawlingHarness, actor: str) -> None:
    party = _live_party(fight.sd, *fight.players)
    for member in fight.players:
        await party.authorize(member)
    await leave(fight.sd, actor, room_io=MagicMock())


async def resolve(fight: MawlingHarness, packets: list[dict]) -> dict:
    result = await fight.command("resolve_phase", {})
    packets.extend(result["packets"])
    return result


async def hit_window(fight: MawlingHarness, packets: list[dict], striker: str) -> dict | None:
    round_number = (await fight.reload()).round_number
    for _ in range(6):
        result = await resolve(fight, packets)
        if result["round"] != round_number:
            return None
        window = result["next"]["waiting_on"]
        if window and (window["actor_id"], window["stage"]) == (striker, "post_roll"):
            return window
    raise AssertionError(f"No hit window or round completion for {striker}")


async def keep_fate(fight: MawlingHarness, packets: list[dict], offer: dict, roller: str, kind: str = "attack") -> None:
    assert (offer["roller_id"], offer["roll_kind"]) == (roller, kind)
    packets.extend((await keep_original(fight, offer))["packets"])


@pytest.mark.parametrize(
    "totals,bark,fate,cancelled",
    [
        pytest.param((17,), False, False, False, id="threshold-ward-expires"),
        pytest.param((None, 25), False, False, False, id="natural-20"),
        pytest.param((17,), True, False, False, id="bark-after-faith-miss"),
        pytest.param((19,), True, True, False, id="bark-and-faith-held"),
        pytest.param((17,), False, False, True, id="cancelled-caster-turn"),
    ],
)
async def test_faith_changes_the_hit_and_expires(
    totals: tuple[int | None, ...], bark: bool, fate: bool, cancelled: bool
) -> None:
    async with faith_fight(*totals, fate=fate) as fight:
        ally, caster, guest = fight.players
        natural = totals[0] is None
        target = participant(await fight.reload(), ally)
        target.ac, target.hp_current = (24, target.hp_current) if natural else (16, 3)
        await fight.persist()
        await defense.declare_attacks(fight, ally)
        packets = await cast(fight, ally, BARK) if bark else await cast(fight, caster)
        if bark:
            await cast(fight, caster, already_open=True)
        if fate:
            await resolve(fight, packets)
            await keep_fate(fight, packets, (await resolve(fight, packets))["fate_offer"], LOOK)
        if (await fight.reload()).beat != "declaration":
            packets += await fight.drain()
        ac = 26 if natural else 20 if bark else 18
        hit = assert_attack(packets, BANDIT, ac, natural, 14 if natural else 0)
        if natural:
            assert (hit["roll"], hit["critical"]) == (20, True)
        else:
            assert hit["attack_total"] == totals[0]
        assert_attack(packets, LOOK, ac, False)
        saved = await assert_faith(fight, packets, caster, ally)
        if not natural:
            assert saved.hp_current == 3
        if bark:
            assert defense.reaction_packet(packets, BARK)["actor_id"] == ally
            assert not saved.bark_skin_active
        if cancelled:
            inspire = {"kind": "ability", "action": "diplomat_inspire", "argument_type": "", "targets": [guest]}
            await declare(fight, {"actor_id": LOOK, **strike(ally, action=SWORD)}, {"actor_id": caster, **inspire})
            await depart(fight, guest)
        else:
            await defense.declare_attacks(fight, ally, LOOK)
        packets = []
        if fate:
            await resolve(fight, packets)
            paused = await resolve(fight, packets)
            if offer := paused.get("fate_offer"):
                await keep_fate(fight, packets, offer, LOOK)
        if (await fight.reload()).beat != "declaration":
            packets += await fight.drain()
        assert not cancelled or any(p.get("outcome") == "target_left" for p in packets)
        assert_attack(packets, LOOK, target.ac, True)
        assert not sources(participant(await fight.reload(), ally))


@pytest.mark.parametrize("excluded", ["too-far", "self", "wall"])
async def test_faith_refuses_excluded_targets(excluded: str) -> None:
    async with faith_fight(20 if excluded == "wall" else 17) as fight:
        ally, caster, _ = fight.players
        state = await fight.reload()
        if excluded == "too-far":
            require_spatial(state)["positions"][caster] = pos(35)
        if excluded == "wall":
            add_wall(state, "thornwall", "Thornwall", pos(0, -4), pos(0, 4), kind=THORNWALL)
        await fight.persist()
        await defense.declare_attacks(fight, {"too-far": ally, "self": caster, "wall": "thornwall"}[excluded], BANDIT)
        packets = []
        window = await hit_window(fight, packets, BANDIT)
        await refuse(fight, caster, window)
        if window:
            packets += await fight.drain()
        assert_attack(packets, BANDIT, 19 if excluded == "wall" else 16, True)


@pytest.mark.parametrize("same_window", [True, False], ids=["first-caster-wards", "warded-ally-refuses"])
async def test_casters_cannot_double_ward(same_window: bool) -> None:
    async with faith_fight(19) as fight:
        ally, caster, guest = fight.players
        first, second = (guest, caster) if same_window else (caster, guest)
        enemies = [BANDIT] if same_window else fight.enemies
        await defense.declare_attacks(fight, ally, *enemies)
        packets = []
        window = await hit_window(fight, packets, BANDIT)
        assert window is not None
        await cast(fight, first, already_open=True)
        if not same_window:
            window = await hit_window(fight, packets, LOOK)
        await refuse(fight, second, window, already_offered=same_window)
        if window:
            packets += await fight.drain()
        for enemy in (BANDIT,) if same_window else fight.enemies:
            assert_attack(packets, enemy, 18, True)
        await assert_faith(fight, packets, first, ally)


async def test_other_recipient() -> None:
    async with faith_fight(19) as fight:
        ally, caster, guest = fight.players
        require_spatial(await fight.reload())["positions"][LOOK] = pos(25, 5)
        await fight.persist()
        bandit = {"actor_id": BANDIT, **strike(ally, action=SWORD)}
        lookout = {"actor_id": LOOK, **strike(caster, action=SWORD)}
        await declare(fight, bandit, lookout)
        packets = await cast(fight, caster)
        window = await hit_window(fight, packets, LOOK)
        assert window and (guest, FAITH) in {(r["actor_id"], r["id"]) for r in window["reactions"]}, packets
        await cast(fight, guest, already_open=True)
        packets += await fight.drain()
        assert_attack(packets, LOOK, 18, True)
        await assert_faith(fight, packets, caster, ally)
        await assert_faith(fight, packets, guest, caster)


@pytest.mark.parametrize("fate", [True, False], ids=["held-followup", "caster-leaves-at-the-riposte-window"])
async def test_departure_preserves_the_original_attack(fate: bool) -> None:
    async with faith_fight(*(18, 5, 17) if fate else (17,), fate=fate, skirmisher=not fate) as fight:
        ally, caster, _ = fight.players
        await defense.declare_attacks(fight, ally)
        packets = await cast(fight, caster)
        result = await resolve(fight, packets)
        if fate:
            await keep_fate(fight, packets, result["fate_offer"], ally, "save")
            offer = (await resolve(fight, packets))["fate_offer"]
            assert (offer["roller_id"], offer["roll_kind"]) == (LOOK, "attack")
        else:
            window = result["next"]["waiting_on"]
            assert (window["actor_id"], window["stage"]) == (BANDIT, "post_reaction_miss")
        await depart(fight, caster)
        if fate:
            await keep_fate(fight, packets, offer, LOOK)
        if (await fight.reload()).beat != "declaration":
            packets += await fight.drain()
        assert_attack(packets, BANDIT, 18, fate)
        assert_attack(packets, LOOK, 18 if fate else 16, not fate)
        await assert_faith(fight, packets, caster, ally, departed=True)
