from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from _zhael_fate_fixtures import game_tools
from _zhael_fate_skills_fixtures import SKILL
from _zhael_unravel_fixtures import activate, opening, patch_player
from _zhael_unravel_fixtures import unravel as unravel
from acceptance import test_departed_member_leaves_fight as departure
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._enemy_opportunity_helpers import move
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
from acceptance.test_taunt import TAUNT
from acceptance.test_valdris_party_yield import ability_action
from acceptance.turn_undead_harness import TurnFight
from combat._round_checkpoint_helpers import Fight
from livekit import rtc
from test_aelora_gift import _live_party

import ability_persistence
import db_mutations
from check_tools import check
from combat_spatial import require_spatial
from combat_state import CombatState
from db_mutations_concentration import update_player_concentration
from participant_lifecycle import _setup_party_join
from query_tools import query_info


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


async def test_departure_of_a_late_joiner_leaves_the_fight_untouched(unravel: Fight) -> None:
    before = await opening(unravel, 0)
    joiner = await unravel.join()
    assert unravel.lifecycle is not None
    await unravel.lifecycle.aclose()
    unravel.lifecycle = _live_party(unravel.session, *unravel.ids)
    assert unravel.session.party.contains(joiner)
    assert unravel.session.combat_state.get_participant(joiner) is None
    await leave_unravel_guest(unravel, joiner)
    assert not unravel.session.party.contains(joiner)
    assert await unravel.reload() == before


async def test_noncombat_departure_keeps_the_fate_cancellation_receipt(unravel: Fight) -> None:
    _, guest = unravel.ids
    spell = "arcane_haste"
    await update_player_concentration(guest, spell, conn=unravel.pool)
    unravel.session.member_state(guest).concentration.spell_id = spell
    call = game_tools(unravel.session, check, query_info)
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        held = await unravel.invoke(call, "check", actor=guest, roll=SKILL)
    assert held["fate_offer"]["roller_id"] == guest
    await leave_unravel_guest(unravel, guest)
    query = await unravel.invoke(call, "query_info", kind="inventory")
    assert query["settled_fate"]["outcome"] == "cancelled"


@pytest.mark.parametrize("ids", ["x", [1], [" "], ["guest", "guest"]], ids=["shape", "type", "blank", "duplicate"])
async def test_reload_refuses_invalid_departure_ids(unravel: Fight, ids: object) -> None:
    saved = await opening(unravel, 0)
    await db_mutations.save_combat_state(saved["combat_id"], {**saved, "departed_player_ids": ids}, conn=unravel.pool)
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


async def test_departure_preserves_the_surviving_warriors_taunt(reset_db_pool) -> None:
    async with defense_fight("warrior") as fight:
        warrior, guest = fight.players
        enemy = fight.enemies[0]
        await ability_persistence.set_elective_equipped(warrior, TAUNT, equipped=True, conn=fight.pool)
        run = Run(fight, GUEST)
        await run.declare(ability_action(warrior, TAUNT, enemy))
        with patch("check_resolution.dice_roll", return_value=_d20(1)):
            await run.resolve()
        await depart_guest(fight, guest)
        target = (await fight.reload()).get_participant(enemy)
        assert target is not None
        (taunt,) = [c for c in target.conditions if c["type"] == "taunted"]
        assert taunt["source"] == warrior


async def test_skeleton_still_fears_its_living_cleric(reset_db_pool) -> None:
    fight = TurnFight()
    try:
        await fight.enter({"skeleton": ("undead", 4)}, ally=True)
        with patch("check_resolution.dice_roll", return_value=_d20(2)):
            effects = fight.cast(await fight.phase(cast=True))["turn_undead"]
        (effect,) = [p for p in effects if p["target_id"] == "skeleton"]
        assert effect["outcome"] == "frightened"
        await depart_guest(fight, fight.players[GUEST])
        skeleton = (await fight.reload()).get_participant("skeleton")
        assert skeleton is not None
        (fear,) = [c for c in skeleton.conditions if c["type"] == "frightened"]
        assert fear["source"] == fight.caster and "turn_undead" in fear
    finally:
        await fight.close()
        await fight.pool.execute("DELETE FROM creatures WHERE id=$1", fight.undead_id)


async def test_departure_preserves_the_survivors_inner_fire_save(reset_db_pool) -> None:
    async with defense_fight("mage", fate=True) as fight:
        host, guest = fight.players
        await patch_architect_player(host, race="draethar")
        with patch("check_resolution.dice_roll", return_value=_d20(5)), patch("dice.roll", return_value=_damage_die(4)):
            held = await fight.command("activate", {"id": "draethar_inner_fire"})
        assert held["fate_offer"]["roller_id"] == host
        await depart_guest(fight, guest)
        cursor = (await fight.reload()).inner_fire_continuation
        assert cursor is not None and cursor["player_id"] == host
        query = await fight.command("query_info", {"kind": "combat"})
        assert query["settled_fate"]["concentration_broken"] == "arcane_fly"


@pytest.mark.parametrize("mover_seat", [PRIMARY, GUEST], ids=["survivor", "leaver"])
async def test_departure_at_an_ally_movement_window(reset_db_pool, mover_seat: int) -> None:
    async with defense_fight(
        "artificer",
        ally_archetype="artificer",
        library=((PRIMARY, "arcane_shield_spell"), (GUEST, "arcane_shield_spell")),
    ) as fight:
        run = Run(fight, GUEST)
        mover = run.players[mover_seat]
        first, second = fight.enemies
        state = await fight.reload()
        require_spatial(state)["positions"].update({mover: pos(0), first: pos(-5), second: pos(-60)})
        await fight.persist()
        await run.declare(move(mover, 25))
        window = await run.pause("pre_roll")
        assert window["target_id"] == mover
        await depart_guest(fight, run.guest)
        saved = await fight.reload()
        if mover == run.guest:
            assert saved.open_window is None
        else:
            assert saved.open_window is not None and saved.open_window["id"] == window["window_id"]
            await departure.finish(run)
            assert require_spatial(await fight.reload())["positions"][mover] == pos(25)


async def test_departure_clears_the_leavers_held_ally_attack(reset_db_pool) -> None:
    async with defense_fight("warrior", fate=True) as fight:
        run = Run(fight, PRIMARY)
        await run.declare(weapon_attack(run.guest, fight.enemies[0], ""))
        with patch("check_resolution.dice_roll", return_value=_d20(12)):
            offer = await run.pause()
        assert offer["roller_id"] == run.guest
        before = (await fight.reload()).ally_continuation
        assert before is not None and before["attack"]
        await depart_guest(fight, run.guest)
        after = (await fight.reload()).ally_continuation
        assert after is not None and after["attack"] == {}
        await departure.finish(run)
        assert not run.hits(run.guest)


async def pause_second_doubt(run: Run, first: str, second: str) -> dict:
    with patch("check_resolution.dice_roll", run.roll):
        run.faces(20, 19, 5, 16)
        await run.pause("post_roll")
        await run.react(first, DOUBT)
        await run.react(second, DOUBT)
        await run.pause()
        offer = await run.pause()
    entries = (await run.fight.reload()).held_actions[0]["disruptions"]
    assert [(e["packet"]["actor_id"], bool(e.get("complete"))) for e in entries] == [(first, True), (second, False)]
    assert offer["roll_kind"] == "save"
    return offer


async def test_other_departure_keeps_the_pending_disruption_save(reset_db_pool) -> None:
    async with disruption() as fight:
        run = Run(fight, THIRD)
        offer = await pause_second_doubt(run, run.guest, run.host)
        await depart_guest(fight, run.guest)
        assert fight.sd.fate_offer is not None and fight.sd.fate_offer.id == offer["offer_id"]
        with patch("check_resolution.dice_roll", run.roll):
            await departure.finish(run)
        (doubt,) = [p for p in run.packets if p.get("ability_id") == DOUBT]
        assert (doubt["actor_id"], doubt["save_roll"], doubt["save_success"]) == (run.host, 5, False)
