import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from itertools import chain, repeat
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance.defensive_reactions_harness import defense_fight, player_row
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_bark_skin import keep_original
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_paladin_oath_swear import patch_player
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_still_anchors import strike
from acceptance.test_valdris_party_yield import ability_action
from test_aelora_gift import _live_party

import ability_persistence
import db_mutations
import db_queries
from combat_phase import PhaseBeat
from combat_state import CombatState

PRIMARY, GUEST, THIRD = 0, 1, 2
POTION = "healing_potion_minor"


def assert_departed(state: CombatState, guest: str) -> None:
    assert state.get_participant(guest) is None and state.spatial is not None
    assert guest in state.departed_player_ids
    assert guest not in (*state.initiative_order, *state.pending_declarations, *state.spatial["positions"])
    assert guest not in state.spatial["speeds"]


def team(
    classes: tuple[str, ...] = ("warrior", "guardian"), **options: Any
) -> Callable[[], AbstractAsyncContextManager[MawlingHarness]]:
    first, second, *extra = classes
    return partial(defense_fight, first, ally_archetype=second, extra_archetypes=tuple(extra), **options)


def swing(actor: str, target: str) -> dict:
    return {"actor_id": actor, **strike(target, action=SWORD)}


class Run:
    def __init__(self, fight: MawlingHarness, leaver: int) -> None:
        self.fight = fight
        self.players = list(fight.players)
        self.guest = self.players[leaver]
        self.host = next(pid for pid in self.players if pid != self.guest)
        self.enemies: list[str] = fight.enemies
        self.dice: Iterator[int] = repeat(16)
        self.packets: list[dict] = []
        self.results: list[dict] = []
        self.before: dict[str, dict] = {}
        self.after: dict[str, dict] = {}

    def faces(self, *faces: int) -> None:
        self.dice = chain(faces, repeat(faces[-1]))

    def roll(self, *_: Any, **__: Any) -> SimpleNamespace:
        return _d20(next(self.dice))

    async def declare(self, *declarations: dict) -> None:
        await self.fight.command("declare_phase", {"declarations": list(declarations)})

    def lost_hp(self, player: str) -> int:
        return self.before[player]["hp"]["current"] - self.after[player]["hp"]["current"]

    async def defend(self) -> None:
        state = await self.fight.reload()
        await self.declare(
            *({"kind": "defend", "actor_id": p.id, "reshape": []} for p in state.participants if not p.is_structure)
        )

    async def react(self, actor: str, ability: str) -> None:
        receipt = await tool_receipt(self.fight, actor, "activate", {"id": ability})
        assert not receipt.is_error, receipt.output

    async def resolve(self) -> dict:
        if offer := self.fight.sd.fate_offer:
            result = await keep_original(self.fight, {"offer_id": offer.id})
        else:
            result = await self.fight.command("resolve_phase", {})
        self.results.append(result)
        self.packets.extend(result["packets"])
        return result

    async def pause(self, stage: str | None = None) -> dict:
        for _ in range(12):
            result = await self.resolve()
            shown = result["next"]["waiting_on"] or {}
            if stage is None and result.get("fate_offer"):
                return result["fate_offer"]
            if stage is not None and stage in (shown.get("stage"), *(r["id"] for r in shown.get("reactions", ()))):
                return shown
        raise AssertionError(f"Did not reach {stage or 'a Fate offer'}")

    def hits(self, actor: str) -> list[dict]:
        return [p for p in self.packets if p["actor_id"] == actor and "hit" in p]

    def target_left(self, actor: str, target: str) -> dict:
        (receipt,) = [p for p in self.packets if p.get("outcome") == "target_left"]
        assert (receipt["actor_id"], receipt["target_id"], receipt["resolved"]) == (actor, target, False)
        return receipt


async def finish(run: Run) -> None:
    for _ in range(12):
        await run.resolve()
        if (await run.fight.reload()).beat == PhaseBeat.DECLARATION:
            return
    raise AssertionError("Next declaration beat was not reached")


@dataclass(frozen=True)
class Row:
    id: str
    fight: Callable[[], AbstractAsyncContextManager[MawlingHarness]]
    prepare: Callable[[Run], Awaitable[None]]
    leaver: int = GUEST
    settle: Callable[[Run], Awaitable[None]] = finish
    check: Callable[[Run, CombatState], None] | None = None


async def run_row(row: Row) -> None:
    async with row.fight() as fight:
        run = Run(fight, row.leaver)
        lifecycle = _live_party(fight.sd, *run.players)
        try:
            assert await lifecycle.authorize(run.guest)
            with patch("check_resolution.dice_roll", run.roll):
                await row.prepare(run)
                run.before = {pid: await player_row(pid) for pid in run.players}
                history = deepcopy((await fight.reload()).round_checkpoints)
                await leave(fight.sd, run.guest, room_io=MagicMock())
                fight.players = [pid for pid in run.players if pid != run.guest]
                assert fight.sd.primary_player_id == run.host
                departed = await fight.reload()
                assert departed.round_checkpoints == history
                assert_departed(departed, run.guest)
                assert run.guest not in departed.reactions_available
                run.results.clear()
                run.packets.clear()
                await row.settle(run)
            state = await fight.reload()
            assert state.beat == PhaseBeat.DECLARATION
            assert_departed(state, run.guest)
            run.after = {pid: await player_row(pid) for pid in run.players}
            before, after = run.before[run.guest], run.after[run.guest]
            assert (after["hp"], after.get("conditions")) == (before["hp"], before.get("conditions"))
            assert all(p["actor_id"] != run.guest for p in run.packets)
            if row.check is not None:
                row.check(run, state)
        finally:
            fight.players = run.players
            await lifecycle.aclose()


def held(stage: str, leaver: int) -> Row:
    classes = ("artificer", "guardian") if leaver == PRIMARY else ("guardian", "artificer")
    fight = team(classes, library=((leaver, "arcane_shield_spell"),))

    async def at_window(run: Run) -> None:
        first, second = run.enemies
        await run.declare(swing(first, run.guest), swing(second, run.host))
        shown = await run.pause(stage)
        assert shown["actor_id"] == first and shown["target_id"] == run.guest

    def check(run: Run, state: CombatState) -> None:
        first, second = run.enemies
        receipt = run.target_left(first, run.guest)
        assert receipt["execution_id"]
        (hit,) = run.hits(second)
        assert run.lost_hp(run.host) == hit["damage"] > 0

    return Row(id=f"held-{stage}-{leaver}", fight=fight, leaver=leaver, prepare=at_window, check=check)


async def queue_attacks(run: Run) -> None:
    first, second = run.enemies
    await run.declare(weapon_attack(run.guest, first, ""), swing(first, run.host), swing(second, run.guest))


def queued_results(run: Run, state: CombatState) -> None:
    first, second = run.enemies
    cancelled = run.target_left(second, run.guest)
    assert [p for p in run.packets if p.get("target_id") == run.guest] == [cancelled]
    (hit,) = run.hits(first)
    assert run.lost_hp(run.host) == hit["damage"] > 0
    enemy = state.get_participant(first)
    assert enemy is not None and enemy.hp_current == enemy.hp_max


async def intercept(run: Run) -> None:
    await run.declare(run.fight.composite([run.host, run.host]), swing(run.enemies[1], run.host))
    await run.pause("post_roll")
    await run.react(run.guest, "guardian_intercept")


def intercepted(run: Run, state: CombatState) -> None:
    assert run.target_left(run.enemies[0], run.guest)["strike_index"] == 0


async def guiding_light(run: Run) -> None:
    await run.declare(ability_action(run.guest, "divine_guiding_light", run.enemies[0]))
    await run.fight.drain()


async def strike_marked_foe(run: Run) -> None:
    await run.declare(weapon_attack(run.host, run.enemies[0], ""))
    run.faces(3, 17, 16)
    await finish(run)
    assert [p["roll"] for p in run.hits(run.host)] == [3]


async def divine_wards(run: Run) -> None:
    cleric = run.players[THIRD]
    await run.declare(
        ability_action(run.guest, "divine_divine_ward", run.host),
        ability_action(cleric, "divine_divine_ward", cleric),
    )
    await run.fight.drain()


async def only_own_ward_left(run: Run) -> None:
    state = await run.fight.reload()
    warded = {p.id for p in state.participants if any(c["type"] == "divine_ward" for c in p.conditions)}
    assert warded == {run.players[THIRD]}
    await run.defend()
    await finish(run)


async def order_potion(run: Run) -> None:
    order = "marshal_field_medic_order"
    await db_mutations.add_inventory_item(run.host, POTION, 1, tainted=False)
    marshal = run.players[GUEST]
    await ability_persistence.set_elective_equipped(marshal, order, equipped=True)
    await run.declare(ability_action(marshal, order, run.host))
    await run.fight.drain()
    await run.declare(
        {
            "kind": "attack_consume",
            "action": "Longsword",
            "actor_id": run.host,
            "target_id": run.enemies[0],
            "item_id": POTION,
            "heal_target_id": marshal,
        }
    )


async def settle_patient_left(run: Run) -> None:
    await finish(run)
    enemy = (await run.fight.reload()).get_participant(run.enemies[0])
    assert enemy is not None and enemy.hp_current == enemy.hp_max
    run.target_left(run.host, run.guest)
    (item,) = [row for row in await db_queries.get_player_inventory(run.host) if row["id"] == POTION]
    assert item["slot_info"]["quantity"] == 1


async def settle_unrelated_leaver(run: Run) -> None:
    marshal = run.players[GUEST]
    state = await run.fight.reload()
    assert state.order_riders[run.host][0]["source_id"] == marshal
    assert state.pending_declarations[run.host]["healing_item"]["target_id"] == marshal
    await finish(run)


async def swear(run: Run) -> None:
    await patch_player(run.guest, **{"class": "paladin", "divine_favor": {"patron": "zhael", "level": 90, "max": 100}})
    choice = json.loads((await tool_receipt(run.fight, run.guest, "query_info", {"kind": "combat"})).output)
    pledge = {"choice_id": choice["oath_choice"]["choice_id"], "option": "timed", "objective_kind": "defeat_target"}
    pledge.update(target_id=run.enemies[0], last_round=4)
    receipt = await tool_receipt(run.fight, run.guest, "select", pledge)
    assert not receipt.is_error, receipt.output


async def reach_oath_deadline(run: Run) -> None:
    for _ in range(5):
        await run.defend()
        await finish(run)


def oath_lapsed(run: Run, state: CombatState) -> None:
    (lapse,) = [change for result in run.results for change in result.get("oath_changes", [])]
    (saved,) = run.after[run.guest]["oaths"]["records"]
    assert (lapse["owner_id"], lapse["new_status"], lapse["round_number"]) == (run.guest, "lapsed", 4)
    assert saved["status"] == "lapsed"
    assert all(run.guest not in checkpoint["players"] for checkpoint in state.round_checkpoints)


medic_fight = team(("warrior", "marshal", "guardian"))
oath_fight = team(("guardian", "guardian"))
guiding_fight = team(("warrior", "cleric"), library=((GUEST, "divine_guiding_light"),))
ward_fight = team(
    ("warrior", "cleric", "cleric"), library=((GUEST, "divine_divine_ward"), (THIRD, "divine_divine_ward"))
)
ROWS = [
    held("pre_roll", PRIMARY),
    held("post_roll", GUEST),
    Row(id="queued-declarations", fight=team(), prepare=queue_attacks, check=queued_results),
    Row(id="intercept", fight=team(enemy="hollow_knight"), prepare=intercept, check=intercepted),
    Row(id="field-medic-1-p1", fight=medic_fight, prepare=order_potion, settle=settle_patient_left),
    Row(
        id="medic-unrelated-leaver",
        fight=medic_fight,
        leaver=THIRD,
        prepare=order_potion,
        settle=settle_unrelated_leaver,
    ),
    Row(id="guiding-light-caster", fight=guiding_fight, prepare=guiding_light, settle=strike_marked_foe),
    Row(id="divine-ward-caster", fight=ward_fight, prepare=divine_wards, settle=only_own_ward_left),
    Row(id="timed-oath-lapses", fight=oath_fight, prepare=swear, settle=reach_oath_deadline, check=oath_lapsed),
]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.id)
async def test_departure(reset_db_pool, row: Row) -> None:
    await run_row(row)
