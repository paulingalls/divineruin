from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from _zhael_unravel_fixtures import activate, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance import test_departed_member_leaves_fight as departure
from acceptance._capstone_helpers import _d20
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.counter_reactions_harness import RIPOSTE, WEAPON, counter_fight
from acceptance.defensive_reactions_harness import declare_attacks, defense_fight, player_row, reload_session
from acceptance.disruption_reactions_harness import DOUBT, ambush, attack_damage, open_stage
from acceptance.mawling_harness import MawlingHarness
from acceptance.test_architect_fight import WORKS, enter, pos
from acceptance.test_architect_terrain import set_favor
from acceptance.test_departed_member_leaves_fight import GUEST, PRIMARY, THIRD, Row, Run, run_row, team
from acceptance.test_guardian_intercept import SWORD, tool_receipt
from acceptance.test_martial_core_kit import weapon_attack
from acceptance.test_paladin_oath_swear import patch_player as patch_architect_player
from acceptance.test_slippery_restrain import advance
from acceptance.test_slippery_restrain import declare as declare_entomb
from acceptance.test_slippery_restrain import mock_combat_agent_factory as mock_combat_agent_factory
from acceptance.test_spell_bless_lifecycle import leave
from acceptance.test_spell_natures_grasp import GRASP, depart_guest
from combat._round_checkpoint_helpers import Fight
from livekit import rtc

import db_mutations
from combat_spatial import require_spatial
from combat_state import CombatState
from db_mutations_concentration import update_player_concentration
from participant_lifecycle import _setup_party_join


async def riposte(run: Run) -> None:
    await declare_attacks(run.fight, run.guest, run.enemies[0])
    run.faces(1, 18)
    await run.pause(RIPOSTE)
    await run.react(run.guest, RIPOSTE)
    await run.pause()


def original_attack(run: Run, state: CombatState) -> None:
    (attack,) = [p for p in run.hits(run.enemies[0]) if p.get("action") == SWORD]
    assert (attack["hit"], attack["roll"]) == (False, 1)
    assert not any(p.get("counter_attack") for p in run.packets)


@asynccontextmanager
async def disruption() -> AsyncIterator[MawlingHarness]:
    async with ambush(DOUBT, fate=True, extra_archetypes=("whisper",)) as fight:
        with attack_damage(12, 7, 6):
            yield fight


async def settled_doubt(run: Run) -> None:
    state = await run.fight.reload()
    caster = state.get_participant(run.guest)
    assert caster is not None
    caster.attributes.update(charisma=24, intelligence=18)
    await run.fight.persist()
    ally = run.players[GUEST]
    await update_player_concentration(ally, "divine_bless", conn=run.fight.pool)
    run.fight.sd.member_state(ally).concentration.spell_id = "divine_bless"
    run.faces(20, 5, 19, 16, 20, 1)
    await run.pause("post_roll")
    await run.react(run.guest, DOUBT)
    await run.react(run.host, DOUBT)
    for _ in range(4):
        await run.resolve()


def no_departed_disruption(run: Run, state: CombatState) -> None:
    (hit,) = run.hits(run.enemies[0])
    ally = run.players[GUEST]
    assert [p["actor_id"] for p in run.packets if p.get("ability_id") == DOUBT] == [run.host]
    assert hit["damage"] == 6 and run.before[ally]["hp"] == run.after[ally]["hp"]


async def wrap_save(run: Run) -> None:
    state = await run.fight.reload()
    for pid in (run.guest, run.host):
        actor = state.get_participant(pid)
        assert actor is not None
        actor.conditions = [{"type": "frightened", "source": run.enemies[0], "duration": None}]
    state.participants.sort(key=lambda p: p.id != run.guest)
    await run.fight.persist()
    await run.defend()
    run.faces(5, 19)
    await run.pause()


def survivor_saved(run: Run, state: CombatState) -> None:
    assert [o["roller_id"] for result in run.results if (o := result.get("fate_offer"))] == [run.host]
    host = state.get_participant(run.host)
    assert host is not None and "frightened" not in {c["type"] for c in host.conditions}


async def echo_strike(run: Run) -> None:
    state = await run.fight.reload()
    echo = state.get_participant(run.guest)
    assert echo is not None
    echo.type = "temporary_hollowed"
    await run.fight.persist()
    await run.declare(weapon_attack(run.guest, run.host, ""))
    await run.pause("pre_roll")


@asynccontextmanager
async def architect_with_rogue() -> AsyncIterator[MawlingHarness]:
    fight = MawlingHarness()
    try:
        await fight.prepare((5, 5), companion=None, location=WORKS)
        await patch_architect_player(fight.players[GUEST], **{"class": "rogue"})
        fight.enemies = [cast(dict, (await enter(fight)).architect_encounter)["owner_id"]]
        with patch("combat_recharge.roll", return_value=SimpleNamespace(total=5)):
            yield fight
    finally:
        await fight.close()


async def entomb(run: Run) -> None:
    state = await run.fight.reload()
    require_spatial(state)["positions"].update({run.guest: pos(5), run.host: pos(40), run.enemies[0]: pos(0)})
    await run.fight.persist()
    await declare_entomb(run.fight, run.enemies[0], run.guest, "Entomb")
    await advance(run.fight, expect_condition_window=True)


def entomb_landed(run: Run, state: CombatState) -> None:
    (receipt,) = [p for p in run.packets if p["actor_id"] == run.enemies[0] and p.get("target_id") == run.guest]
    assert receipt.get("outcome") is None
    assert receipt["condition_inflicted"] == "restrained" and receipt["save_success"] is False


counterattack = partial(counter_fight, RIPOSTE, gear=WEAPON, fate=True)
echo_fight = team(("artificer", "guardian"), library=((PRIMARY, "arcane_shield_spell"),))
ROWS = [
    Row(id="counteractor", fight=counterattack, leaver=PRIMARY, prepare=riposte, check=original_attack),
    Row(id="doubt-True", fight=disruption, leaver=THIRD, prepare=settled_doubt, check=no_departed_disruption),
    Row(id="wrap-save-in-flight", fight=team(fate=True), prepare=wrap_save, check=survivor_saved),
    Row(id="echo-hold", fight=echo_fight, prepare=echo_strike),
    Row(id="landed-entomb", fight=architect_with_rogue, prepare=entomb, check=entomb_landed),
]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.id)
async def test_departure(reset_db_pool, row: Row) -> None:
    await run_row(row)


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


@pytest.mark.parametrize("ids", ["x", [1], [" "], ["guest", "guest"]], ids=["shape", "type", "blank", "duplicate"])
async def test_reload_refuses_invalid_departure_ids(unravel: Fight, ids: object) -> None:
    await opening(unravel, 0)
    state = unravel.session.combat_state
    assert state is not None
    await db_mutations.save_combat_state(state.combat_id, {**state.to_dict(), "departed_player_ids": ids})
    with pytest.raises(ValueError, match="Invalid departed player IDs"):
        await unravel.reload()


async def test_later_caster_departure_keeps_the_current_approach_save(reset_db_pool) -> None:
    library = ((GUEST, GRASP), (THIRD, GRASP))
    async with defense_fight("druid", ally_archetype="druid", extra_archetypes=("druid",), library=library) as fight:
        host, *reactors = fight.players
        first, later = sorted(reactors)
        mover = fight.enemies[0]
        await set_favor(fight, "zhael", 40)
        state = await fight.reload()
        require_spatial(state)["positions"].update({mover: pos(35), host: pos(5), first: pos(0, 5), later: pos(0, -5)})
        await fight.persist()
        await reload_session(fight)
        await declare_attacks(fight, host, mover)
        with patch("check_resolution.dice_roll", return_value=_d20(4)):
            await open_stage(fight, "movement")
            for caster in (first, later):
                receipt = await tool_receipt(fight, caster, "activate", {"id": GRASP})
                assert not receipt.is_error, receipt.output
            assert (await fight.command("resolve_phase", {}))["fate_offer"]["roll_kind"] == "save"
        await depart_guest(fight, later)
        with patch("check_resolution.dice_roll", return_value=_d20(18)):
            query = await fight.command("query_info", {"kind": "combat"})
        packets = query["settled_fate"]["packets"]
        (grasp,) = [p for p in packets if p.get("ability_id") == GRASP]
        assert (grasp["actor_id"], grasp["condition_inflicted"], grasp["save"]["roll"]) == (first, "restrained", 4)
