"""Shield of Faith through registered combat tools, saved state, turn boundaries and departure."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import chain, repeat
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.counter_reactions_harness import WEAPON
from acceptance.defensive_reactions_harness import defense_fight, reload_session
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import blow, keep_original
from acceptance.test_guardian_intercept import BANDIT, SWORD, tool_receipt
from acceptance.test_opportunity_strike import participant
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_spell_reaction_offers import resources
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

from check_resolution import D20Roll
from combat_spatial import require_spatial
from combat_structures import THORNWALL, add_wall

FAITH, WARD, BARK, LOOK = "divine_shield_of_faith", "shield_of_faith", "warden_bark_skin", "lookout"
ALLY, CASTER_1, CASTER_2, WALL = 0, 1, 2, "thornwall"  # party seats, and a structure that can be struck
START = "start"  # a step key that acts after declarations, before the round resolves


class Step(StrEnum):
    FAITH = "spend Shield of Faith"
    BARK = "the ally spends Bark Skin"
    DENY = "Faith is not offered and activation is refused"
    LATE = "Faith was offered but is refused as already warded"
    LEAVE = "the seat leaves the party"


@dataclass(frozen=True)
class Natural:
    face: int


@dataclass(frozen=True)
class Blow:
    ac: int
    hit: bool
    damage: int | None = None  # None: not asserted


@dataclass(frozen=True)
class Setup:
    ally: str = "warden"
    fate: bool = False
    ally_ac: int = 16
    ally_hp: int | None = None
    caster_distance: int = 25
    wall: bool = False
    lookout_at: tuple[int, int] = (-5, 5)
    rolls: tuple[int | Natural, ...] = (17,)  # d20 totals in order; the last one repeats


@dataclass(frozen=True, kw_only=True)
class Round:
    strikes: Sequence[tuple[str, int | str]]  # (enemy, struck seat)
    steps: dict = field(default_factory=dict)  # (actor, window stage or Fate roll kind) or START -> [(Step, seat)]
    expect: dict[str, Blow] = field(default_factory=dict)
    wards: Sequence[int] = ()  # seats whose Faith remains on the ally at round end
    inspire: tuple[int, int] | None = None  # (seat, target seat) declares diplomat_inspire


HIT, MISS = Blow(16, True, 7), Blow(18, False, 0)  # unwarded hit; warded miss
WARDED_HIT, BOTH_WARDS = Blow(18, True, 7), Blow(20, False, 0)  # +2 still hit; Bark and Faith +4 miss
BOTH = [(BANDIT, ALLY), (LOOK, ALLY)]
BANDIT_HIT, LOOKOUT_HIT = (BANDIT, "post_roll"), (LOOK, "post_roll")  # post-roll windows on each enemy's hit


def case(name: str, setup: Setup, *rounds: Round):
    return pytest.param(setup, list(rounds), id=name)


def ward_sources(state, actor):
    return [c["originating_participant_id"] for c in participant(state, actor).conditions if c["type"] == WARD]


class Flow:
    """Runs a round through resolve_phase, keeping every Fate roll and taking each step at its key."""

    def __init__(self, fight):
        self.fight, self.party, self.spent, self.packets = fight, None, {}, []

    def seat(self, key):
        return key if isinstance(key, str) else self.fight.players[key]

    async def act(self, step, seat, window):
        fight, actor = self.fight, self.seat(seat)
        if step == Step.LEAVE:
            self.party = self.party or _live_party(fight.sd, *fight.players)
            for member in fight.players:
                await self.party.authorize(member)
            return await leave(fight.sd, actor, room_io=MagicMock())
        offered = (actor, FAITH) in {(offer["actor_id"], offer["id"]) for offer in window["reactions"]}
        before = await resources(fight, actor)
        receipt = await tool_receipt(fight, actor, "activate", {"id": BARK if step == Step.BARK else FAITH})
        await reload_session(fight)
        after = await resources(fight, actor)
        if step in (Step.DENY, Step.LATE):
            assert receipt.is_error and offered == (step == Step.LATE) and after == before, receipt.output
            assert step == Step.DENY or "already warded" in receipt.output
            assert not (await fight.reload()).reactions_available.get(actor, {}).get("spent")
            return
        focus, resonance = before
        assert not receipt.is_error and after == (focus - 2, resonance + (step == Step.FAITH)), receipt.output
        if step == Step.FAITH:
            self.spent[actor] = window["target_id"]

    async def round(self, plan: Round):
        fight, steps = self.fight, dict(plan.steps)
        declarations = [{"actor_id": enemy, **strike(self.seat(seat), action=SWORD)} for enemy, seat in plan.strikes]
        if plan.inspire:
            caster, target = plan.inspire
            inspire = {"kind": "ability", "action": "diplomat_inspire", "argument_type": ""}
            declarations.append({"actor_id": self.seat(caster), **inspire, "targets": [self.seat(target)]})
        await fight.command("declare_phase", {"declarations": declarations})
        for step, seat in steps.pop(START, ()):
            await self.act(step, seat, None)
        start = fight.sd.combat_state.round_number
        result = await fight.command("resolve_phase", {})
        for _ in range(20):
            self.packets += result["packets"]
            if (await fight.reload()).round_number != start:
                # No window opens when no one may react, so a refusal is checked after the round.
                for step, seat in chain(*steps.values()):
                    assert step == Step.DENY, steps
                    await self.act(step, seat, {"reactions": []})
                return
            offer, window = result.get("fate_offer"), result["next"]["waiting_on"]
            if offer:
                key = (offer["roller_id"], offer["roll_kind"])
            else:
                key = window and (window["actor_id"], window["stage"])
            for step, seat in steps.pop(key, ()):
                await self.act(step, seat, window)
            result = await (keep_original(fight, offer) if offer else fight.command("resolve_phase", {}))
        raise AssertionError("round did not finish")


CASES = [
    case(
        "threshold-ward-expires",
        Setup(ally_hp=3),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)]},
            expect={BANDIT: MISS, LOOK: MISS},
            wards=[CASTER_1],
        ),
        Round(strikes=[(BANDIT, ALLY)], expect={BANDIT: Blow(16, True)}),
    ),
    case(
        "too-far",
        Setup(caster_distance=35),
        Round(strikes=[(BANDIT, ALLY)], steps={BANDIT_HIT: [(Step.DENY, CASTER_1)]}, expect={BANDIT: HIT}),
    ),
    case(
        "self",
        Setup(),
        Round(strikes=[(BANDIT, CASTER_1)], steps={BANDIT_HIT: [(Step.DENY, CASTER_1)]}, expect={BANDIT: HIT}),
    ),
    case(
        "wall",
        Setup(wall=True, rolls=(20,)),
        Round(
            strikes=[(BANDIT, WALL)], steps={BANDIT_HIT: [(Step.DENY, CASTER_1)]}, expect={BANDIT: Blow(19, True, 7)}
        ),
    ),
    case(
        "natural-20",
        Setup(ally_ac=24, rolls=(Natural(20), 25)),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)]},
            expect={BANDIT: Blow(26, True), LOOK: Blow(26, False, 0)},
            wards=[CASTER_1],
        ),
    ),
    case(
        "bark-after-faith-miss",
        Setup(),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.BARK, ALLY), (Step.FAITH, CASTER_1)]},
            expect={BANDIT: BOTH_WARDS, LOOK: BOTH_WARDS},
            wards=[CASTER_1],
        ),
    ),
    case(
        "bark-and-faith-held",
        Setup(fate=True, rolls=(19,)),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.BARK, ALLY), (Step.FAITH, CASTER_1)]},
            expect={BANDIT: BOTH_WARDS, LOOK: BOTH_WARDS},
            wards=[CASTER_1],
        ),
    ),
    case(
        "first-caster-wards",
        Setup(rolls=(19,)),
        Round(
            strikes=[(BANDIT, ALLY)],
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_2), (Step.LATE, CASTER_1)]},
            expect={BANDIT: WARDED_HIT},
            wards=[CASTER_2],
        ),
    ),
    case(
        "warded-ally-refuses",
        Setup(rolls=(19,)),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)], LOOKOUT_HIT: [(Step.DENY, CASTER_2)]},
            expect={BANDIT: WARDED_HIT, LOOK: WARDED_HIT},
            wards=[CASTER_1],
        ),
    ),
    case(
        "other-recipient",
        Setup(rolls=(19,), lookout_at=(25, 5)),
        Round(
            strikes=[(BANDIT, ALLY), (LOOK, CASTER_1)],
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)], LOOKOUT_HIT: [(Step.FAITH, CASTER_2)]},
            expect={LOOK: WARDED_HIT},
            wards=[CASTER_1],
        ),
    ),
    case(
        "cancelled-caster-turn",
        Setup(),
        Round(
            strikes=[(BANDIT, ALLY)],
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)]},
            expect={BANDIT: MISS},
            wards=[CASTER_1],
        ),
        Round(
            strikes=[(LOOK, ALLY)],
            steps={START: [(Step.LEAVE, CASTER_2)]},
            expect={LOOK: HIT},
            inspire=(CASTER_1, CASTER_2),
        ),
    ),
    case(
        "held-followup",
        Setup(fate=True, rolls=(18, 5, 17)),
        Round(
            strikes=BOTH,
            steps={BANDIT_HIT: [(Step.FAITH, CASTER_1)], (LOOK, "attack"): [(Step.LEAVE, CASTER_1)]},
            expect={BANDIT: Blow(18, True), LOOK: MISS},
        ),
    ),
    case(
        "caster-leaves-at-the-riposte-window",
        Setup(ally="skirmisher"),
        Round(
            strikes=BOTH,
            steps={
                BANDIT_HIT: [(Step.FAITH, CASTER_1)],
                (BANDIT, "post_reaction_miss"): [(Step.LEAVE, CASTER_1)],
            },
            expect={BANDIT: MISS, LOOK: HIT},
        ),
    ),
]


async def place(fight, setup: Setup):
    state = await fight.reload()
    for actor in fight.players:
        participant(state, actor).ac = 16
    ally = participant(state, fight.players[ALLY])
    ally.ac = setup.ally_ac
    if setup.ally_hp is not None:
        ally.hp_current = setup.ally_hp
    if setup.wall:
        add_wall(state, WALL, "Thornwall", pos(0, -4), pos(0, 4), kind=THORNWALL)
    positions = require_spatial(state)["positions"]
    positions.update({fight.players[CASTER_1]: pos(setup.caster_distance), fight.players[ALLY]: pos(0)})
    positions[LOOK] = pos(*setup.lookout_at)
    await fight.persist()


def fixed_d20(rolls):
    totals = chain(rolls, repeat(rolls[-1]))

    def roll(self, _rng=None):
        total = next(totals)
        return self.evaluate(total.face if isinstance(total, Natural) else total - self.modifier)

    return patch.object(D20Roll, "roll", roll)


@pytest.mark.parametrize(("setup", "rounds"), CASES)
async def test_shield_of_faith(reset_db_pool, setup: Setup, rounds: list[Round]):
    async with defense_fight(
        setup.ally,
        ally_archetype="diplomat",
        extra_archetypes=("marshal",),
        library=((CASTER_1, FAITH), (CASTER_2, FAITH)),
        fate=setup.fate,
        gear=WEAPON if setup.ally == "skirmisher" else None,
    ) as fight:
        await place(fight, setup)
        flow = Flow(fight)
        with fixed_d20(setup.rolls), patch("check_resolution_attack.dice_roll", return_value=_damage_die(7)):
            for plan in rounds:
                mark = len(flow.packets)
                await flow.round(plan)
                for enemy, expected in plan.expect.items():
                    attack = blow(flow.packets[mark:], enemy)
                    assert attack["resolved"]
                    assert (attack["target_ac"], attack["hit"]) == (expected.ac, expected.hit)
                    assert expected.damage is None or attack["damage"] == expected.damage
                state = await fight.reload()
                assert ward_sources(state, fight.players[ALLY]) == [fight.players[seat] for seat in plan.wards]
        receipts = {
            p["actor_id"]: (p["target_id"], p["ac_bonus"]) for p in flow.packets if p.get("ability_id") == FAITH
        }
        assert receipts == {actor: (target, 2) for actor, target in flow.spent.items()}
        inspired = any(plan.inspire for plan in rounds)
        assert any(p.get("outcome") == "target_left" for p in flow.packets) == inspired
