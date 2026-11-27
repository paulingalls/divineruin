"""Departure rows. A row builds a fight and runs its script; ``leave`` departs the leaver, every resolve after it
reloads the saved state, and ``finish`` must reach the next declaration beat. Then the row's checks run. Ids:
``guest`` (the leaver), ``host``, ``e0``/``e1`` (enemies), ``p0``-``p2`` (seats). Declarations: ``e0>guest`` a sword
swing, ``host>e0`` a weapon attack, ``p0>e0+p2`` that attack with a potion for p2, ``guest*spell>host,e0`` an
ability, ``guest~25`` a move to x=25. ``faces 3 17`` sets the d20 faces, and the last one repeats."""

import json
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance._enemy_opportunity_helpers import move
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.test_architect_fight import pos
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_paladin_oath_swear import patch_player
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_still_anchors import strike
from test_aelora_gift import _live_party

import ability_persistence
import db_mutations
import db_queries
from combat_phase import PhaseBeat
from combat_state import CombatState
from db_mutations_concentration import update_player_concentration

POTION = "healing_potion_minor"


def assert_departed(state: CombatState, guest: str) -> None:
    assert state.get_participant(guest) is None and state.spatial is not None
    assert guest not in (*state.initiative_order, *state.pending_declarations, *state.spatial["positions"])
    assert guest not in state.spatial["speeds"]


def team(classes: str = "warrior guardian", **options: Any) -> Callable:
    first, second, *extra = classes.split()
    return lambda: defense_fight(first, ally_archetype=second, extra_archetypes=tuple(extra), **options)


class Run:
    def __init__(self, fight, leaver: int) -> None:
        self.fight, self.players, self.e = fight, list(fight.players), fight.enemies
        self.guest = self.players[leaver]
        self.host = next(p for p in self.players if p != self.guest)
        self.faces: Iterator[int] = iter(())
        self.last = 16
        self.offer: Any = None
        self.state: Any = None
        self.results, self.packets, self.before, self.after = [], [], {}, {}

    def id(self, token: str) -> str:
        if token in ("guest", "host"):
            return getattr(self, token)
        return {"e": self.e, "p": self.players}[token[0]][int(token[1:])] if token[1:].isdigit() else token

    def left(self) -> list[tuple]:
        return [(p["actor_id"], p["target_id"]) for p in self.packets if p.get("outcome") == "target_left"]

    def hits(self, actor: str) -> list[dict]:
        return [p for p in self.packets if p["actor_id"] == self.id(actor) and "hit" in p]

    def hp(self, pid: str, *, before: bool = False) -> int:
        return (self.before if before else self.after)[self.id(pid)]["hp"]["current"]

    def p(self, pid: str):
        return self.state.get_participant(self.id(pid))


def declaration(run: Run, token: str) -> dict:
    actor, _, target = token.partition(">")
    actor, _, spell = actor.partition("*")
    target, _, patient = target.partition("+")
    if "~" in actor:
        return move(run.id(actor.split("~")[0]), float(actor.split("~")[1]))
    if spell:
        targets = [run.id(t) for t in target.split(",")]
        return {"kind": "ability", "actor_id": run.id(actor), "action": spell, "targets": targets, "argument_type": ""}
    if patient:
        potion = {"kind": "attack_consume", "action": "Longsword", "item_id": POTION, "heal_target_id": run.id(patient)}
        return {**potion, "actor_id": run.id(actor), "target_id": run.id(target)}
    if actor[0] == "e":
        return {"actor_id": run.id(actor), **strike(run.id(target), action=SWORD)}
    return weapon_attack(run.id(actor), run.id(target), "")


async def resolve(run: Run) -> dict:
    offer = run.offer if run.fight.sd.fate_offer is not None else None
    result = await (keep_original(run.fight, offer) if offer else run.fight.command("resolve_phase", {}))
    run.results.append(result)
    run.packets += result["packets"]
    run.offer = result.get("fate_offer")
    return result


def edit(change: Callable[[Run, Any], object]) -> Callable:
    async def apply(run: Run) -> None:
        change(run, await run.fight.reload())
        await run.fight.persist()

    return apply


async def step(run: Run, line: str) -> None:
    verb, *args = line.split()
    fight = run.fight
    if verb in ("window", "offer", "finish"):
        for _ in range(12):
            result = await resolve(run)
            shown = result["next"]["waiting_on"] or {}
            ended = fight.sd.combat_state is None or (await fight.reload()).beat == PhaseBeat.DECLARATION
            if verb == "finish" and ended:
                return
            if verb == "offer" and result.get("fate_offer"):
                return
            if verb == "window" and args[0] in (shown.get("stage"), *(r["id"] for r in shown.get("reactions", ()))):
                return
        raise AssertionError(f"{line!r} was not reached")
    if verb == "declare":
        await fight.command("declare_phase", {"declarations": [declaration(run, token) for token in args]})
    elif verb == "defend":
        actors = [p.id for p in (await fight.reload()).participants if not p.is_structure]
        defend = [{"kind": "defend", "actor_id": actor, "reshape": []} for actor in actors]
        await fight.command("declare_phase", {"declarations": defend})
    elif verb == "faces":
        run.faces, run.last = iter([int(face) for face in args[:-1]]), int(args[-1])
    elif verb == "react":
        receipt = await tool_receipt(fight, run.id(args[0]), "activate", {"id": args[1]})
        assert not receipt.is_error, receipt.output
        run.offer = json.loads(receipt.output).get("fate_offer") or run.offer
    elif verb == "resolve":
        await resolve(run)
    elif verb == "drain":
        run.packets += await fight.drain()
        run.results.append(fight.last_result)
    elif verb == "place":
        spots = {run.id(k): pos(*map(float, v.split(","))) for k, v in (token.split("=") for token in args)}
        await edit(lambda r, state: state.spatial["positions"].update(spots))(run)
    elif verb == "elective":
        await ability_persistence.set_elective_equipped(run.id(args[0]), args[1], equipped=True)
    elif verb == "concentrate":
        await update_player_concentration(run.id(args[0]), args[1], conn=fight.pool)
        fight.sd.member_state(run.id(args[0])).concentration.spell_id = args[1]
    elif verb == "stock":
        await db_mutations.add_inventory_item(run.id(args[0]), POTION, 1, tainted=False)
    else:
        raise AssertionError(f"Unknown step {line!r}")


CHECKS: dict[str, Callable[..., bool]] = {
    "left": lambda r, *pairs: r.left() == [tuple(map(r.id, pair.split(">"))) for pair in pairs],
    "dealt": lambda r, actor: sum(p.get("damage", 0) for p in r.hits(actor)) > 0,
    "whole": lambda r, pid: r.p(pid).hp_current == r.p(pid).hp_max,
    "ac": lambda r, actor, pid: [p["target_ac"] for p in r.hits(actor)] == [r.p(pid).ac],
    "roll": lambda r, actor, face: [p["roll"] for p in r.hits(actor)] == [int(face)],
    "has": lambda r, pid, kind: kind in {c["type"] for c in r.p(pid).conditions},
    "lacks": lambda r, pid, kind: kind not in {c["type"] for c in r.p(pid).conditions},
    "offers": lambda r, *who: [o["roller_id"] for x in r.results if (o := x.get("fate_offer"))] == [*map(r.id, who)],
    "unspent": lambda r, pid: r.after[r.id(pid)]["focus"] == r.before[r.id(pid)]["focus"],
    "untargeted": lambda r, pid: all(p.get("target_id") != r.id(pid) for p in r.packets),
    "orderless": lambda r: not r.state.order_riders,
}


def items(script: str | tuple) -> list[Any]:
    parts = script if isinstance(script, tuple) else (script,)
    return [y for x in parts for y in ([s.strip() for s in x.split(";") if s.strip()] if isinstance(x, str) else [x])]


@dataclass(frozen=True)
class Row:
    id: str
    harness: Callable
    script: str | tuple
    expect: str | tuple = ()
    leaver: int = 1
    rolls: tuple = ()


async def depart(run: Run) -> None:
    run.before = {pid: await player_row(pid) for pid in run.players}
    history = deepcopy((await run.fight.reload()).round_checkpoints)
    await leave(run.fight.sd, run.guest, room_io=MagicMock())
    run.fight.players = [pid for pid in run.players if pid != run.guest]
    assert (await run.fight.reload()).round_checkpoints == history
    run.results, run.packets = [], []


async def run_row(row: Row) -> Run:
    async with row.harness() as fight:
        run = Run(fight, row.leaver)
        lifecycle = _live_party(fight.sd, *fight.players)
        await lifecycle.authorize(run.guest)
        script = items(row.script)
        script += [] if "leave" in script else ["leave", "finish"]
        try:
            with ExitStack() as stack:
                face = lambda *_, **__: _d20(next(run.faces, run.last))  # noqa: E731
                stack.enter_context(patch("check_resolution.dice_roll", face))
                for extra in row.rolls:
                    stack.enter_context(extra())
                for item in script:
                    await (depart(run) if item == "leave" else step(run, item) if isinstance(item, str) else item(run))
            run.state = await fight.reload()
            run.after = {pid: await player_row(pid) for pid in run.players}
        finally:
            fight.players = run.players
            await lifecycle.aclose()
    assert_departed(run.state, run.guest)
    guest_after, guest_before = run.after[run.guest], run.before[run.guest]
    assert (guest_after["hp"], guest_after.get("conditions")) == (guest_before["hp"], guest_before.get("conditions"))
    assert all(p["actor_id"] != run.guest for p in run.packets)
    for check in items(row.expect):
        verb, *args = check.split() if isinstance(check, str) else ("", None)
        assert check(run) if callable(check) else CHECKS[verb](run, *args), (check, run.packets)
    return run


async def potion_kept(run: Run) -> None:
    (item,) = [i for i in await db_queries.get_player_inventory(run.players[0]) if i["id"] == POTION]
    assert item["slot_info"]["quantity"] == 1


def medic(leaver: int, patient: str, expect: str) -> Row:
    order = "stock p0; elective p1 marshal_field_medic_order; declare p1*marshal_field_medic_order>p0; drain"
    script = (order, f"declare p0>e0+{patient}; leave; finish", potion_kept)
    return Row(f"field-medic-{leaver}-{patient}", team("warrior marshal guardian"), script, expect, leaver)


async def swear(run: Run) -> None:
    await patch_player(run.guest, **{"class": "paladin", "divine_favor": {"patron": "zhael", "level": 90, "max": 100}})
    choice = json.loads((await tool_receipt(run.fight, run.guest, "query_info", {"kind": "combat"})).output)
    pledge = {"choice_id": choice["oath_choice"]["choice_id"], "option": "timed", "objective_kind": "defeat_target"}
    receipt = await tool_receipt(run.fight, run.guest, "select", {**pledge, "target_id": run.e[0], "last_round": 4})
    assert not receipt.is_error, receipt.output


def lapsed(r: Run) -> bool:
    (lapse,) = [change for result in r.results for change in result.get("oath_changes", [])]
    (saved,) = r.after[r.guest]["oaths"]["records"]
    when = (lapse["owner_id"], lapse["new_status"], lapse["round_number"], saved["status"])
    kept = [c for c in r.state.round_checkpoints if r.guest in c["players"]]
    return when == (r.guest, "lapsed", 4, "lapsed") and not kept


def held(stage: str, leaver: int) -> Row:
    shielded = team(("artificer guardian", "guardian artificer")[leaver], library=((leaver, "arcane_shield_spell"),))
    script = f"declare e0>guest e1>host; window {stage}"
    return Row(f"held-{stage}-{leaver}", shielded, script, "left e0>guest; dealt e1", leaver)


def cleric(spell: str = "", classes: str = "warrior cleric") -> Callable:
    return team(classes, library=((classes.split().index("cleric"), spell),) if spell else ())


BLESS, BLESSER = "declare host*divine_bless>", cleric("divine_bless", "cleric guardian")
INTERCEPT = "declare e0>host e1>host; window post_roll; react guest guardian_intercept"
FAITH = "declare e0>host; window pre_roll; react guest cleric_shield_of_faith"
GUIDE = "declare guest*divine_guiding_light>e0; drain; leave; declare host>e0; faces 3 17 16; finish"
WARD = "declare guest*divine_divine_ward>host; drain; leave; defend; finish"
COORDINATE = "declare p0*marshal_coordinated_assault>p1,p2; drain; leave; defend; finish"
ROWS = [
    held("pre_roll", 0),
    held("post_roll", 1),
    Row("queued-declarations", team(), "declare guest>e0 e0>host e1>guest", "left e1>guest; dealt e0; whole e0"),
    medic(1, "p2", "dealt p0; left"),
    medic(1, "p1", "whole e0; left p0>p1"),
    Row("ally-cast-both", BLESSER, BLESS + "host,guest", "has host blessed"),
    Row("ally-cast-guest", BLESSER, BLESS + "guest", "unspent host; left host>guest"),
    Row("intercept", team(), INTERCEPT, "left e0>guest"),
    Row("shield-of-faith", cleric(), FAITH, "ac e0 host"),
    Row("guiding-light-caster", cleric("divine_guiding_light"), GUIDE, "roll host 3"),
    Row("divine-ward-caster", cleric("divine_divine_ward"), WARD, "lacks host divine_ward"),
    Row("timed-oath-lapses", team("guardian guardian"), (swear, "leave", *["defend; drain"] * 5), (lapsed,)),
    Row("fate-held-strike", team(fate=True), "declare e0>guest e1>host; faces 20 2; offer", "left e0>guest"),
    Row("coordinated-partner", team("marshal warrior guardian"), COORDINATE, "orderless"),
]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.id)
async def test_departure(reset_db_pool, row: Row) -> None:
    await run_row(row)
