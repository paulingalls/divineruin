"""Bless through registered spell casts and reloaded saving throws."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from _zhael_fate_fixtures import game_tools
from _zhael_unravel_fixtures import GIFT
from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._spell_hostile_condition_helpers import add_player, attack, cast_spell, defend, play, reload, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.seeds import seed_player_with_pools
from acceptance.test_spell_new_conditions import equip
from combat._round_checkpoint_helpers import Fight
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from sample_fixtures import make_context, make_mock_room
from test_aelora_gift import _live_party
from voice_condition_fixtures import participant
from weapon_fixtures import DAGGER

import combat_turn
import db
import db_mutations
import db_mutations_conditions
from activate_tools import activate
from check_payloads import SaveCheck
from check_tools import check
from session_end import run_guest_departure

BLESS = "divine_bless"
DETECT = "arcane_detect_magic"


async def ooc_player(*known_spells):
    pid = f"bless_{uuid4().hex}"
    await seed_player_with_pools(await db.get_pool(), player_id=pid, class_="cleric", known_spells=known_spells)
    return pid


def context(pid):
    return make_context(pid, room=make_mock_room())


async def save_total(pid, *, ctx=None):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(10)),
        patch("condition_bonus.dice_roll", return_value=_d20(3)),
    ):
        roll = SaveCheck(kind="save", save_type="wisdom", dc=12, effect_on_fail="resist")
        return json.loads(await check(ctx or context(pid), roll))["total"]


async def test_bless_survives_reloaded_saves_until_ooc_replacement(dev_db_pool):
    caster, control = await ooc_player(BLESS, DETECT), await ooc_player()
    ctx = context(caster)
    await activate(ctx, BLESS)
    baseline = await save_total(control)
    assert await save_total(caster) == baseline + 3
    assert await save_total(caster) == baseline + 3
    assert (await saved_player(caster))["conditions"][0]["sustaining_caster_ids"] == [caster]

    await activate(ctx, DETECT)
    player = await saved_player(caster)
    assert player["concentration"]["spell_id"] == DETECT
    assert player["conditions"] == []
    assert await save_total(caster) == baseline


@pytest.mark.parametrize("caster_is_host", [False, True])
async def test_bless_ends_when_its_caster_leaves_the_party(dev_db_pool, caster_is_host):
    caster, ally = await ooc_player(BLESS), await ooc_player()
    host, guest = (caster, ally) if caster_is_host else (ally, caster)
    ctx = make_context(host, room=make_mock_room(), party_member_ids=[guest])
    sd = ctx.userdata
    lifecycle = _live_party(sd, host, guest)
    try:
        generation = await lifecycle.authorize(caster)
        assert generation is not None
        baseline = await save_total(ally)
        with sd._bind_authenticated_actor(caster, generation, lifecycle.require_authorized):
            await game_tools(sd, activate)("activate", id=BLESS, target_id=ally)
        assert await save_total(ally) == baseline + 3

        await leave(sd, caster, ctx.session.room_io)
        assert sd.party.member_ids == [ally]
        assert (await saved_player(ally))["conditions"] == []
        assert (await saved_player(caster))["concentration"]["spell_id"] is None
        assert await save_total(ally) == baseline
    finally:
        await lifecycle.aclose()


async def leave(sd, caster, room_io=None):
    sd.departing_player_id = caster
    with (
        patch("session_end.generate_session_summary", return_value={"summary": "Farewell"}),
        patch("session_end.room_admin.remove_player"),
        patch("host_handoff.transfer_room"),
    ):
        await run_guest_departure(sd, caster, SimpleNamespace(room_io=room_io))


async def blessed_fight_without_caster(fight: Fight, *, legacy: bool = False) -> int:
    import character_spells

    ally, caster = fight.ids
    sd = fight.session
    baseline = await save_total(ally)
    await character_spells.record_learned(caster, BLESS, "discovery", conn=fight.pool)
    await fight.invoke(game_tools(sd, activate), "activate", actor=caster, id=BLESS, target_id=ally)
    await fight.start()
    await fight.declare()
    await fight.finish_round(2)
    assert participant(sd.combat_state, ally).conditions[0]["sustaining_caster_ids"] == [caster]
    assert len(sd.combat_state.round_checkpoints) == 2
    if legacy:
        row = await fight.row()
        del row["encounter_facts"]
        for checkpoint in row["round_checkpoints"]:
            del checkpoint["combat"]["encounter_facts"]
        await fight.write_row(row)
        await fight.reload()
    await leave(sd, caster)
    return baseline


async def test_combat_departure_releases_carried_bless_and_keeps_checkpoints(unravel):
    fight = unravel
    ally, caster = fight.ids
    sd = fight.session
    baseline = await blessed_fight_without_caster(fight)
    await fight.reload()
    assert all(c["type"] != "blessed" for c in participant(sd.combat_state, ally).conditions)
    assert (await saved_player(caster))["concentration"]["spell_id"] is None
    assert await save_total(ally) == baseline
    # Enemy pockets, timed oaths and Unravel Fate still read the round history.
    assert [c["round_number"] for c in sd.combat_state.round_checkpoints] == [1, 2]


@pytest.mark.parametrize("legacy", [False, True], ids=["current", "legacy"])
async def test_unravel_after_departure_does_not_restore_the_departed_bless(unravel: Fight, legacy: bool) -> None:
    fight = unravel
    ally, caster = fight.ids
    sd = fight.session
    baseline = await blessed_fight_without_caster(fight, legacy=legacy)
    if legacy:
        checkpoints = (await fight.row())["round_checkpoints"]
        assert [c["combat"]["encounter_facts"]["party_aggressors"] for c in checkpoints] == [None, None]
    await fight.call("activate", id=GIFT)
    assert sd.combat_state.round_number == 1
    if legacy:
        assert (await fight.row())["encounter_facts"]["party_aggressors"] is None
    assert all(c["type"] != "blessed" for c in participant(sd.combat_state, ally).conditions)
    assert (await saved_player(caster))["concentration"]["spell_id"] is None
    await fight.reload()
    assert all(c["type"] != "blessed" for c in participant(sd.combat_state, ally).conditions)
    assert await save_total(ally) == baseline


def swing(packets, actor):
    return next(packet for packet in packets if packet["actor_id"] == actor and "hit" in packet)


async def test_bless_applies_to_each_attack_hit_and_miss(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally, control = await add_player(ctx, "warrior"), await add_player(ctx, "warrior")
    foe = await set_foe(ctx)
    for pid in (ally, control):
        await equip(ctx, pid, dict(DAGGER))
    foe.ac = 16
    await db_mutations.save_combat_state(ctx.userdata.combat_state.combat_id, ctx.userdata.combat_state.to_dict())
    await play(ctx, cast_spell(caster, BLESS, ally), defend(control), defend("foe"))
    with patch("condition_bonus.dice_roll", return_value=_d20(3)):
        for face, hits in ((17, True), (2, False)):
            packets, state = await play(
                ctx,
                defend(caster),
                attack(ally, "Training Blade", foe.id),
                attack(control, "Training Blade", foe.id),
                defend(foe.id),
                face=face,
            )
            blessed, plain = swing(packets, ally), swing(packets, control)
            assert blessed["roll"] == plain["roll"] == face
            assert blessed["hit"] == hits
            assert blessed["attack_total"] == plain["attack_total"] + 3
            assert "blessed" not in blessed.get("consumed_conditions", ())
        assert participant(state, ally).conditions[0]["sustaining_caster_ids"] == [caster]
    ally_ctx, control_ctx = context(ally), context(control)
    for bonus in (3, 3, 0):
        if bonus == 0:
            packets, _ = await play(
                ctx,
                defend(caster),
                defend(ally),
                defend(control),
                attack(foe.id, foe.action_pool[0]["name"], caster),
                faces=[19, 1],
            )
            broken = next(packet for packet in packets if packet["actor_id"] == foe.id)
            assert broken["concentration_broken"] == BLESS
        ally_ctx.userdata.combat_state = await reload(ctx)
        control_ctx.userdata.combat_state = ally_ctx.userdata.combat_state
        assert await save_total(ally, ctx=ally_ctx) == await save_total(control, ctx=control_ctx) + bonus


async def test_held_bless_attack_keeps_the_original_die(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await set_foe(ctx)
    opening, _ = await play(ctx, attack(caster, "Training Blade", "foe"), defend("foe"), face=17)
    baseline = swing(opening, caster)["attack_total"] - 17
    await play(ctx, cast_spell(caster, BLESS, caster), defend("foe"))
    player = await saved_player(caster)
    await (await db.get_pool()).execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
        caster,
        '{"patron":"zhael","level":40,"max":100}',
    )
    await combat_turn.declare_phase(ctx, [attack(caster, "Training Blade", "foe"), defend("foe")])
    with (
        patch("condition_bonus.dice_roll", return_value=_d20(3)),
        patch("check_resolution.dice_roll", return_value=_d20(20)),
    ):
        async with ctx.userdata.fate_lock:
            offered = json.loads(await combat_turn.resolve_phase(ctx))["fate_offer"]
    await reload(ctx)
    with (
        patch("condition_bonus.dice_roll", return_value=_d20(1)),
        patch("check_resolution.dice_roll", return_value=_d20(2)),
    ):
        async with ctx.userdata.fate_lock:
            kept = json.loads(await activate(ctx, "zhael_fates_thread", offer_id=offered["offer_id"], keep="original"))
        await _resolve_round(ctx)
    assert swing(kept["packets"], caster)["attack_total"] == 20 + baseline + 3
    state = await reload(ctx)
    assert participant(state, caster).conditions[0]["sustaining_caster_ids"] == [caster]
    assert (await saved_player(caster))["concentration"] == player["concentration"]
    with patch("condition_bonus.dice_roll", return_value=_d20(3)):
        ordinary, _ = await play(ctx, attack(caster, "Training Blade", "foe"), defend("foe"), face=17)
    assert swing(ordinary, caster)["attack_total"] == 17 + baseline + 3


async def test_migration_clears_only_legacy_bless_from_players_and_checkpoints(spell_fight):
    ctx = spell_fight
    caster, owned = ctx.userdata.player_id, await ooc_player()
    legacy, control = await ooc_player(), await ooc_player()
    old = {"type": "blessed", "duration": None, "source": BLESS}
    sustained = {**old, "sustaining_caster_ids": [caster]}
    unrelated = {"type": "exhausted", "duration": None, "source": "travel", "stacks": 1}
    pool = await db.get_pool()
    await db_mutations_conditions.save_player_conditions(legacy, [old], conn=pool)
    await db_mutations_conditions.save_player_conditions(owned, [sustained, unrelated], conn=pool)
    state = ctx.userdata.combat_state
    participant(state, caster).conditions = [old, unrelated]
    image = state.to_dict()
    image.pop("round_checkpoints")
    state.round_checkpoints = [
        {"combat_id": state.combat_id, "round_number": state.round_number, "combat": image, "players": {}}
    ]
    await db_mutations.save_combat_state(state.combat_id, state.to_dict(), conn=pool)

    migration = Path(__file__).resolve().parents[4] / "scripts/migrations/069_bless_sustaining_casters.sql"
    await pool.execute(migration.read_text())
    assert (await saved_player(legacy))["conditions"] == []
    assert (await saved_player(owned))["conditions"] == [sustained, unrelated]
    saved = await reload(ctx)
    assert participant(saved, caster).conditions == [unrelated]
    checkpoint = saved.round_checkpoints[0]["combat"]
    assert next(p for p in checkpoint["participants"] if p["id"] == caster)["conditions"] == [unrelated]
    assert await save_total(legacy) == await save_total(control)


async def test_bless_replacement_leaves_one_caster_until_combat_ends(unravel):
    from _zhael_fate_fixtures import defend as defend_packet
    from _zhael_unravel_fixtures import patch_player

    import character_spells
    from combat_end import end_combat

    fight = unravel
    second, first = fight.ids
    await patch_player(fight, second, focus={"current": 10, "max": 10})
    for pid, spells in ((first, (BLESS, DETECT)), (second, (BLESS,))):
        for spell in spells:
            await character_spells.record_learned(pid, spell, "discovery", conn=fight.pool)
    await fight.invoke(game_tools(fight.session, activate), "activate", actor=first, id=BLESS, target_id=first)
    await fight.start()
    for caster, spell, targets in ((second, BLESS, [first]), (first, DETECT, [])):
        state = fight.session.combat_state
        await fight.declare(
            {"kind": "ability", "actor_id": caster, "action": spell, "targets": targets, "argument_type": ""},
            *(defend_packet(p.id) for p in state.participants if p.id != caster),
        )
        await fight.finish_round(state.round_number + 1)
        live = fight.session.combat_state.get_participant(first)
        expected = sorted([first, second]) if spell == BLESS else [second]
        assert [c["sustaining_caster_ids"] for c in live.conditions if c["type"] == "blessed"] == [expected]
    assert (await saved_player(first))["conditions"][0]["sustaining_caster_ids"] == [first]
    await fight.invoke(game_tools(fight.session, end_combat), "end_combat", outcome="fled")
    assert (await saved_player(first))["conditions"] == []
    assert (await saved_player(second))["concentration"]["spell_id"] is None

    control = await ooc_player()
    assert await save_total(first) == await save_total(control)
