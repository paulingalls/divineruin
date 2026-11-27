"""Bless through registered spell casts and reloaded saving throws."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from _zhael_unravel_fixtures import unravel as unravel
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._spell_hostile_condition_helpers import add_player, attack, cast_spell, defend, play, reload, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.seeds import seed_player_with_pools
from acceptance.test_spell_new_conditions import equip
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from sample_fixtures import make_context, make_mock_room
from voice_condition_fixtures import participant
from weapon_fixtures import DAGGER

import combat_turn
import db
import db_mutations
import db_mutations_conditions
from activate_tools import activate
from check_payloads import SaveCheck
from check_tools import check

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
    for _ in range(2):
        ally_ctx, control_ctx = context(ally), context(control)
        ally_ctx.userdata.combat_state = await reload(ctx)
        control_ctx.userdata.combat_state = ally_ctx.userdata.combat_state
        assert await save_total(ally, ctx=ally_ctx) == await save_total(control, ctx=control_ctx) + 3


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


async def test_combat_reconcile_keeps_only_the_surviving_caster(unravel):
    from _zhael_fate_fixtures import defend as defend_packet
    from _zhael_fate_fixtures import game_tools
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
    assert (await saved_player(first))["conditions"][0]["sustaining_caster_ids"] == [second]

    control = await ooc_player()
    plain = await save_total(control)
    assert await save_total(first) == plain + 3
    await character_spells.record_learned(second, DETECT, "discovery", conn=fight.pool)
    await fight.invoke(game_tools(fight.session, activate), "activate", actor=second, id=DETECT)
    assert (await saved_player(first))["conditions"] == []
    assert await save_total(first) == plain
