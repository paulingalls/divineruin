"""Shield of Faith through registered combat tools, saved state, turn boundaries and departure."""

from functools import partial
from itertools import chain, repeat
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _damage_die
from acceptance.counter_reactions_harness import RIPOSTE, WEAPON, react
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
NAMES, STAGES = {"B": BANDIT, "L": LOOK, "w": "thornwall"}, {"hit": "post_roll", "miss": "post_reaction_miss"}
faith_fight = partial(
    defense_fight, ally_archetype="diplomat", extra_archetypes=("marshal",), library=((1, FAITH), (2, FAITH))
)


def parse(text):
    """'B0 i12; B@hit=faith:1,late:2; B=18/0/0 L=16/1; 1' reads: the bandit strikes seat 0 and seat 1
    inspires seat 2; at the bandit's post-roll window seat 1 spends Faith, then seat 2 is refused; the bandit's
    blow is (target AC, hit, damage), the lookout's (AC, hit); seat 1's ward remains on seat 0 at round end.
    Steps: faith, bark, deny (not offered), late (offered, already warded), leave, riposte; @start acts first."""
    strikes, events, outcomes, wards = (part.split() for part in text.split(";"))
    seat = lambda token: NAMES.get(token) or int(token)  # noqa: E731
    events = dict(event.split("=") for event in events)
    return (
        [(seat(token[0]) if token[0] != "i" else int(token[1]), seat(token[-1])) for token in strikes],
        {(NAMES[k[0]], STAGES.get(k[2:], k[2:])) if k[0] != "@" else k[1:]: v.split(",") for k, v in events.items()},
        {NAMES[k]: tuple(int(v) for v in val.split("/")) for k, val in (o.split("=") for o in outcomes)},
        [int(seat) for seat in wards],
    )


def case(name, setup, *rounds):
    return pytest.param(setup, [parse(text) for text in rounds], id=name)


def ward_sources(state, actor):
    return [c["originating_participant_id"] for c in participant(state, actor).conditions if c["type"] == WARD]


class Flow:
    """Seat 0 is the struck ally; seats 1 and 2 hold Faith. Steps act at a window, a Fate offer or round start."""

    def __init__(self, fight):
        self.fight, self.party, self.spent, self.packets = fight, None, {}, []

    def seat(self, key):
        return key if isinstance(key, str) else self.fight.players[key]

    async def act(self, step, window):
        fight, (verb, _, seat) = self.fight, step.partition(":")
        actor = fight.players[int(seat or 0)]
        if verb == "leave":
            self.party = self.party or _live_party(fight.sd, *fight.players)
            for member in fight.players:
                await self.party.authorize(member)
            return await leave(fight.sd, actor, room_io=MagicMock())
        if verb == "riposte":
            return await react(fight, RIPOSTE)
        offered = (actor, FAITH) in {(o["actor_id"], o["id"]) for o in window["reactions"]}
        before = await resources(fight, actor)
        receipt = await tool_receipt(fight, actor, "activate", {"id": BARK if verb == "bark" else FAITH})
        await reload_session(fight)
        after = await resources(fight, actor)
        if verb in ("deny", "late"):
            assert receipt.is_error and offered == (verb == "late") and after == before, receipt.output
            assert verb == "deny" or "already warded" in receipt.output
            assert not (await fight.reload()).reactions_available.get(actor, {}).get("spent")
        else:
            assert not receipt.is_error and after == (before[0] - 2, before[1] + (verb == "faith")), receipt.output
            if verb == "faith":
                self.spent[actor] = window["target_id"]

    async def round(self, strikes, events):
        fight, events, inspire = self.fight, dict(events), dict(kind="ability", action="diplomat_inspire")
        declarations = [
            {"actor_id": self.seat(a), **inspire, "targets": [self.seat(t)], "argument_type": ""}
            if isinstance(a, int)
            else {"actor_id": a, **strike(self.seat(t), action=SWORD)}
            for a, t in strikes
        ]
        await fight.command("declare_phase", {"declarations": declarations})
        for step in events.pop("start", ()):
            await self.act(step, None)
        start, result = fight.sd.combat_state.round_number, await fight.command("resolve_phase", {})
        for _ in range(20):
            self.packets += result["packets"]
            if (await fight.reload()).round_number != start:
                for step in chain(*events.values()):  # no window opens when no one may react
                    assert step.startswith("deny"), events
                    await self.act(step, {"reactions": []})
                return
            offer, window = result.get("fate_offer"), result["next"]["waiting_on"]
            key = (
                (offer["roller_id"], offer["roll_kind"]) if offer else window and (window["actor_id"], window["stage"])
            )
            for step in events.pop(key, ()):
                await self.act(step, window)
            result = await (keep_original(fight, offer) if offer else fight.command("resolve_phase", {}))
        raise AssertionError("round did not finish")


CASES = [
    case("threshold-ward-expires", {"hp": 3}, "B0 L0; B@hit=faith:1; B=18/0/0 L=18/0/0; 1", "B0; ; B=16/1;"),
    case("too-far", {"dist": 35}, "B0; B@hit=deny:1; B=16/1/7;"),
    case("self", {}, "B1; B@hit=deny:1; B=16/1/7;"),
    case("wall", {"wall": True, "faces": (20,)}, "Bw; B@hit=deny:1; B=19/1/7;"),
    case("natural-20", {"ac": 24, "faces": ("nat20", 25)}, "B0 L0; B@hit=faith:1; B=26/1 L=26/0/0; 1"),
    case("bark-after-faith-miss", {}, "B0 L0; B@hit=bark,faith:1; B=20/0/0 L=20/0/0; 1"),
    case("bark-faith-held", {"fate": True, "faces": (19,)}, "B0 L0; B@hit=bark,faith:1; B=20/0/0 L=20/0/0; 1"),
    case("first-caster-wards", {"faces": (19,)}, "B0; B@hit=faith:2,late:1; B=18/1/7; 2"),
    case("warded-refuses", {"faces": (19,)}, "B0 L0; B@hit=faith:1 L@hit=deny:2; B=18/1/7 L=18/1/7; 1"),
    case(
        "other-recipient",
        {"faces": (19,), LOOK: (25, 5)},
        "B0 L1; B@hit=faith:1 L@hit=faith:2; L=18/1/7; 1",
    ),
    case("cancelled-caster-turn", {}, "B0; B@hit=faith:1; B=18/0/0; 1", "i12 L0; @start=leave:2; L=16/1/7;"),
    case(
        "held-followup",
        {"fate": True, "faces": (18, 5, 17)},
        "B0 L0; B@hit=faith:1 L@attack=leave:1; B=18/1 L=18/0/0;",
    ),
    case(
        "riposte-after-leave",
        {"ally": "skirmisher"},
        "B0 L0; B@hit=faith:1 B@miss=leave:1,riposte; B=18/0/0 L=16/1/7;",
    ),
]


@pytest.mark.parametrize(("setup", "rounds"), CASES)
async def test_shield_of_faith(reset_db_pool, setup, rounds):
    ally = setup.get("ally", "warden")
    gear, fate = WEAPON if ally == "skirmisher" else None, setup.get("fate", False)
    async with faith_fight(ally, fate=fate, gear=gear) as fight:
        flow, state = Flow(fight), await fight.reload()
        for actor in fight.players:
            participant(state, actor).ac = 16
        target = participant(state, fight.players[0])
        target.ac, target.hp_current = setup.get("ac", 16), setup.get("hp", target.hp_current)
        if setup.get("wall"):
            add_wall(state, "thornwall", "Thornwall", pos(0, -4), pos(0, 4), kind=THORNWALL)
        positions = require_spatial(state)["positions"]
        positions.update({fight.players[1]: pos(setup.get("dist", 25)), fight.players[0]: pos(0)})
        positions[LOOK] = pos(*setup.get(LOOK, (-5, 5)))
        await fight.persist()
        faces = chain(setup.get("faces", (17,)), repeat(setup.get("faces", (17,))[-1]))
        roll = lambda self, _rng=None: self.evaluate(20 if (t := next(faces)) == "nat20" else t - self.modifier)  # noqa: E731
        dice = patch("check_resolution_attack.dice_roll", return_value=_damage_die(7))
        with patch.object(D20Roll, "roll", roll), dice:
            for strikes, events, outcomes, wards in rounds:
                mark = len(flow.packets)
                await flow.round(strikes, events)
                for enemy, outcome in outcomes.items():
                    attack = blow(flow.packets[mark:], enemy)
                    got = (attack["target_ac"], attack["hit"], attack["damage"])
                    assert attack["resolved"] and got[: len(outcome)] == outcome
                assert ward_sources(await fight.reload(), fight.players[0]) == [fight.players[i] for i in wards]
        wards = [p for p in flow.packets if p.get("ability_id") == FAITH]
        receipts = {p["actor_id"]: (p["target_id"], p["ac_bonus"]) for p in wards}
        assert receipts == {actor: (target, 2) for actor, target in flow.spent.items()}
        assert all("counter_attack" in p for p in flow.packets if p.get("ability_id") == RIPOSTE)
        inspired = any(isinstance(actor, int) for strikes, *_ in rounds for actor, _ in strikes)
        assert any(p.get("outcome") == "target_left" for p in flow.packets) == inspired
