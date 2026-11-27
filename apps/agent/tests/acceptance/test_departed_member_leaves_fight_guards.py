"""Departure rows with their own fights or setup steps, then the rewind cases. The Zhael rewind harness drives a
session without the fight surface the row builder needs, so those stay ordinary tests."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from _zhael_unravel_fixtures import activate, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance import test_departed_member_leaves_fight as departure
from acceptance._capstone_helpers import _damage_die
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.counter_reactions_harness import RIPOSTE, WEAPON, counter_fight
from acceptance.defensive_reactions_harness import SPELL, player_row
from acceptance.disruption_reactions_harness import DOUBT, ambush, attack_damage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, enter, pos
from acceptance.test_architect_legendary import spend
from acceptance.test_architect_terrain import set_favor
from acceptance.test_departed_member_leaves_fight import Row, Run, edit, step, team
from acceptance.test_guardian_intercept import SWORD
from acceptance.test_slippery_restrain import advance
from acceptance.test_slippery_restrain import declare as declare_entomb
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_valdris_party_yield import ability_action
from acceptance.turn_undead_harness import TurnFight
from combat._round_checkpoint_helpers import Fight
from livekit import rtc

from participant_lifecycle import _setup_party_join


@asynccontextmanager
async def architect(rogue: bool = False):
    fight = MawlingHarness()
    try:
        await fight.prepare((5, 5) if rogue else (20, 20), companion=None, location=WORKS)
        if rogue:
            await departure.patch_player(fight.players[1], **{"class": "rogue"})
        fight.enemies = [cast(dict, (await enter(fight)).architect_encounter)["owner_id"]]
        yield fight
    finally:
        await fight.close()


@asynccontextmanager
async def turning():
    fight = TurnFight()
    try:
        await fight.enter({"skeleton": ("undead", 4)}, ally=True)
        yield fight
    finally:
        await fight.close()
        await fight.pool.execute("DELETE FROM creatures WHERE id=$1", fight.undead_id)


def frighten(*who: str, fallen: bool = False):
    def change(run: Run, state) -> None:
        fear = {"type": "frightened", "source": run.e[0], "duration": None}
        for token in who:
            state.get_participant(run.id(token)).conditions = [fear]
        state.participants.sort(key=lambda p: p.id != run.guest)
        if fallen:
            state.get_participant(run.guest).hp_current, state.get_participant(run.guest).is_fallen = 0, True

    return edit(change)


def doubt(concentration: bool) -> Row:
    def landed(r: Run) -> bool:
        (hit,) = [p for p in r.packets if p["actor_id"] == r.e[0] and "damage" in p]
        quiet = not [p for p in r.packets if p.get("ability_id") == DOUBT]
        lost = r.hp("p1", before=True) - r.hp("p1")
        return quiet and (hit["damage"], lost) == ((6, 0) if concentration else (19, 19))

    smart = edit(lambda r, s: s.get_participant(r.guest).attributes.update(charisma=24, intelligence=18))
    script = (
        "concentrate p1 divine_bless; " * concentration
        + f"faces 20 5 19 16 1; window post_roll; react guest {DOUBT}; resolve"
        + "; resolve" * 2 * concentration
    )
    harness = lambda: ambush(DOUBT, fate=True, extra_archetypes=("whisper",))  # noqa: E731
    return Row(f"doubt-{concentration}", harness, (smart, script), (landed,), 2, (lambda: attack_damage(12, 7, 6),))


def riposte_kept(r: Run) -> bool:
    (attack,) = [p for p in r.packets if p["actor_id"] == r.e[0] and p.get("action") == SWORD]
    return (attack["hit"], attack["roll"]) == (False, 1) and not any(p.get("counter_attack") for p in r.packets)


def warmed(r: Run) -> bool:
    (entry,) = [entry for p in r.packets for entry in p.get("hearthfire_entries", [])]
    moved = r.state.spatial["positions"][r.e[0]]["x"] == pytest.approx(-10)
    return moved and [entry[k] for k in ("source_id", "mover_id", "dc", "success")] == [r.guest, r.e[0], 12, False]


def reshape(guest_first: bool, at_guest: bool) -> Row:
    async def setup(run: Run) -> None:
        first, second = (run.guest, run.host) if guest_first else (run.host, run.guest)
        await edit(lambda r, s: s.participants.sort(key=lambda p: p.id != first))(run)
        await step(run, f"place {first}=6 {second}=7 e0=5,0,5")
        await set_favor(run.fight, "zhael", 40)
        floor = [{"kind": "open_floor", "min": pos(5, -5), "max": pos(7, 5)}]
        defend = {"kind": "defend", "actor_id": run.e[0], "reshape": floor}
        await run.fight.command("declare_phase", {"declarations": [defend]})
        await run.fight.command("resolve_phase", {})

    def floor(r: Run) -> bool:
        (shape,) = [shape for p in r.packets for shape in p.get("reshape", [])]
        results = {result["target_id"]: result for result in shape["results"]}
        guest = {"damage": 8} if guest_first and not at_guest else {"outcome": "target_left"}
        pits = r.state.architect_encounter["pits"] == {r.host: shape["section_id"]}
        return pits and results[r.host]["damage"] == 8 and guest.items() <= results[r.guest].items()

    script = (setup, "faces 1; resolve" + ("" if at_guest and guest_first else "; resolve"))
    rolls = (lambda: patch("architect_reshape.dice.roll", return_value=_damage_die(8)),)
    return Row(f"reshape-{guest_first}-{at_guest}", architect, script, (floor,), rolls=rolls)


async def entomb(run: Run) -> None:
    await step(run, "place guest=5 host=40 e0=0")
    await declare_entomb(run.fight, run.e[0], run.guest, "Entomb")
    await advance(run.fight, expect_condition_window=True)


def entombed(r: Run) -> bool:
    (cast_,) = [p for p in r.packets if p["actor_id"] == r.e[0] and p.get("target_id") == r.guest]
    return [cast_.get(k) for k in ("outcome", "condition_inflicted", "save_success")] == [None, "restrained", False]


async def geometry(run: Run) -> None:
    await edit(lambda r, s: setattr(s.get_participant(r.guest), "reaction_ids", []))(run)
    await step(run, "place guest=15,5")
    await step(run, "concentrate guest divine_bless")
    await set_favor(run.fight, "zhael", 40)
    held = await spend(run.fight, run.e[0], "Geometry Strike", target=run.guest)
    assert (held["fate_offer"]["roll_kind"], held["fate_offer"]["roller_id"]) == ("save", run.guest)


async def turn(run: Run) -> None:
    turned = run.fight.cast(await run.fight.phase(cast=True))["turn_undead"]
    assert {row["target_id"]: row["outcome"] for row in turned}["skeleton"] == "frightened"


async def undead_swing(run: Run) -> None:
    swing = {**run.fight.attack("skeleton"), "target_id": run.host}
    await run.fight.command("declare_phase", {"declarations": [swing]})


def unafraid(r: Run) -> bool:
    (swing,) = r.hits("skeleton")
    return swing["hit"] and not swing.get("fled") and r.hp("host", before=True) - r.hp("host") == swing["damage"]


async def hearth(run: Run) -> None:
    await departure.patch_player(run.guest, divine_favor={"patron": "aelora", "level": 90, "max": 100})
    await edit(lambda r, s: s.get_participant(r.guest).attributes.update(wisdom=16))(run)


MOVER = "place host=30 guest=0 e0=-5 e1=-60; declare guest~25; offer"
WRAP = "defend; faces 5 19; offer"
RECHARGE = (lambda: patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)),)
ECHO = edit(lambda r, s: setattr(s.get_participant(r.guest), "type", "temporary_hollowed"))
SHIELDED = team("artificer guardian", library=((0, "arcane_shield_spell"),))
GEOMETRY_DAMAGE = (lambda: patch("dice.roll", return_value=_damage_die(4)),)
HEARTH = "place host=0 guest=5 e0=-25; react guest aelora_hearthfire; leave; declare e0~-5; faces 1; finish"
TAUNT = "elective guest warrior_taunt; declare guest*warrior_taunt>e0; faces 1; drain; leave; declare e0>host"
DRAETHAR = lambda r: departure.patch_player(r.guest, race="draethar")  # noqa: E731
FIRE = "faces 5; react guest draethar_inner_fire; leave; defend; finish"
RIPOSTE_HELD = f"declare e0>guest; faces 1 18; window {RIPOSTE}; react guest {RIPOSTE}; offer"
ROWS = [
    Row("counteractor", lambda: counter_fight(RIPOSTE, gear=WEAPON, fate=True), RIPOSTE_HELD, (riposte_kept,), 0),
    doubt(False),
    doubt(True),
    Row("wrap-save-in-flight", team(fate=True), (frighten("guest", "host"), WRAP), "offers host"),
    Row("wrap-host-pending", team(fate=True), (frighten("guest", "host"), WRAP + "; resolve"), "lacks host frightened"),
    Row("wrap-death-save", team(fate=True), (frighten("host", fallen=True), "defend; faces 5; offer")),
    Row("inner-fire", team(fate=True), (DRAETHAR, f"concentrate guest {SPELL}; " + FIRE)),
    Row("mover-offer", team(fate=True), MOVER, "untargeted guest"),
    Row("hearthfire-source", team("warrior warden"), (hearth, HEARTH), (warmed,)),
    Row("taunt-source", team("guardian warrior"), (TAUNT, "faces 16; finish"), "dealt e0"),
    Row("echo-hold", SHIELDED, (ECHO, "declare guest>host; window pre_roll")),
    reshape(guest_first=True, at_guest=False),
    reshape(guest_first=True, at_guest=True),
    Row("landed-entomb", lambda: architect(rogue=True), (entomb,), (entombed,), rolls=RECHARGE),
    Row("legendary-fate", architect, (geometry, "leave; resolve; defend; finish"), rolls=GEOMETRY_DAMAGE),
    Row("turned-undead", turning, ("faces 2", turn, "leave", undead_swing, "faces 18; finish"), (unafraid,), 0),
]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.id)
async def test_departure(reset_db_pool, row: Row) -> None:
    await departure.run_row(row)


async def leave_unravel_guest(fight: Fight, guest: str) -> None:
    assert fight.lifecycle is not None and await fight.lifecycle.authorize(guest)
    await leave(fight.session, guest)


async def test_departure_and_rejoin_survive_rewind_at_an_untouched_opening(unravel: Fight) -> None:
    host, guest = unravel.ids
    await opening(unravel, 0)
    original = deepcopy(unravel.session.combat_state.round_checkpoints[-1]["players"])
    await patch_player(unravel, host, focus={"current": 2, "max": 10})
    await patch_player(unravel, guest, hp={"current": 7, "max": 20})
    await unravel.declare()
    await unravel.finish_round(2)
    await leave_unravel_guest(unravel, guest)
    assert unravel.lifecycle is not None
    await unravel.lifecycle.aclose()
    unravel.session.room.remote_participants = {host: SimpleNamespace(identity=host)}
    unravel.lifecycle = _setup_party_join(unravel.session.room, unravel.session)
    unravel.lifecycle._on_connected(cast(rtc.RemoteParticipant, SimpleNamespace(identity=guest)))
    assert await unravel.lifecycle.authorize(guest) and unravel.session.party.contains(guest)
    await patch_player(unravel, guest, hp={"current": 6, "max": 20})
    before = await player_row(guest)
    await activate(unravel)
    assert (await unravel.reload())["round_number"] == 1
    departure.assert_departed(unravel.session.combat_state, guest)
    assert (await player_row(host))["focus"] == original[host]["data"]["focus"]
    assert await player_row(guest) == before
    await unravel.declare()
    await unravel.finish_round(2)
    departure.assert_departed(unravel.session.combat_state, guest)
    saved = await player_row(guest)
    assert (saved["hp"], saved.get("conditions")) == (before["hp"], before.get("conditions"))


async def test_order_from_departed_marshal_is_removed_on_reload_and_rewind(unravel: Fight) -> None:
    host, guest = unravel.ids
    await patch_player(unravel, guest, **{"class": "marshal", "level": 8})
    await opening(unravel, 0)
    foe = next(p.id for p in unravel.session.combat_state.participants if p.type == "enemy")
    await unravel.declare(ability_action(guest, "marshal_direct_strike", host, foe))
    await unravel.finish_round(2)
    assert unravel.session.combat_state.order_riders[host][0]["source_id"] == guest
    await unravel.declare()
    await unravel.finish_round(3)
    await leave_unravel_guest(unravel, guest)
    await unravel.reload()
    await activate(unravel)
    state = await unravel.reload()
    assert state["round_number"] == 2 and host not in state["order_riders"]
    departure.assert_departed(unravel.session.combat_state, guest)
