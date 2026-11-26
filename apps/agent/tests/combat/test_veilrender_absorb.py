"""Absorption at the real cast's recipient landing boundary."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _enemy, _resolve_round
from combat.test_spell_damage_lands import load_combat, prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from creature_combat_helpers import catalog
from creature_combat_helpers import participant as enemy_participant
from voice_condition_fixtures import participant, place_actors

import combat_turn
from creature_combat import translate_creature
from declaration_payloads import AbilityDecl, AttackDecl


async def prepare_absorb(ctx, spell_id="arcane_magic_missile", hp=70, targets=None):
    spell = await prepare_spell(ctx, spell_id)
    state = ctx.userdata.combat_state
    row = next(r for r in catalog() if r["id"] == "hollow_veilrender")
    boss = enemy_participant(translate_creature(row, encounter_id="absorb", enemy_id="foe", role="standard"))
    boss.hp_current = hp
    state.participants[1] = boss
    place_actors(state)
    await combat_turn.declare_phase(
        ctx,
        [
            AbilityDecl(
                kind="ability",
                actor_id=ctx.userdata.player_id,
                action=spell.id,
                targets=targets if targets is not None else ["foe"],
                argument_type="",
            ),
            AttackDecl(
                quick_fingers_mode="",
                quick_fingers_item="",
                reshape=[],
                kind="attack",
                actor_id="foe",
                action="Reality Crush",
                target_id=ctx.userdata.player_id,
                held_item_id="",
                rider="",
            ),
        ],
    )
    return spell


async def ally_cast(ctx):
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1)),
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        result = json.loads(await combat_turn.resolve_phase(ctx))
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    return cast


@pytest.mark.parametrize(
    "spell_id,hp,expected",
    [
        ("arcane_magic_missile", 70, 76),
        ("arcane_magic_missile", 119, 120),
        ("arcane_bolt", 70, 70),
        ("divine_bless", 70, 76),
    ],
)
async def test_absorbed_cast_heals_charges_and_reports(spell_fight, spell_id, hp, expected):
    ctx = spell_fight
    spell = await prepare_absorb(ctx, spell_id, hp)
    before = await saved_player(ctx.userdata.player_id)
    cast = await ally_cast(ctx)
    loaded = await load_combat(ctx.userdata.combat_state.combat_id)
    boss = participant(loaded, "foe")
    assert boss.hp_current == expected
    assert not boss.conditions and not boss.radiant_suppression_pending
    assert not any(e["name"] == "Absorb Magic" for e in boss.deferred_effects)
    assert boss.deferred_effects
    assert loaded.to_dict() == ctx.userdata.combat_state.to_dict()
    assert "damage_result" not in cast and "condition_applied" not in cast
    assert cast["absorbed"] == [
        {"effect": "Absorb Magic", "target_id": "foe", "healed": expected - hp, "hp_current": expected}
    ]
    assert "no effect" in cast["narration_cue"] and "foe" in cast["narration_cue"]
    after = await saved_player(ctx.userdata.player_id)
    assert after["focus"]["current"] == before["focus"]["current"] - spell.focus_cost
    generated = 0 if spell_id == "arcane_bolt" else 2
    assert cast["resonance_generated"] == generated
    assert after.get("resonance", {}).get("current", 0) == ctx.userdata.resonance.current == generated
    assert ctx.userdata.concentration.spell_id == (spell.id if spell.concentration else None)


async def test_bless_keeps_other_recipient_once(spell_fight):
    ctx = spell_fight
    pid = ctx.userdata.player_id
    await prepare_absorb(ctx, "divine_bless", targets=["foe", pid])
    cast = await ally_cast(ctx)
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(state, "foe").hp_current == 76
    assert participant(state, "foe").conditions == []
    assert any(c["type"] == "blessed" for c in participant(state, pid).conditions)
    assert cast["condition_targets"] == [pid] and len(cast["absorbed"]) == 1


@pytest.mark.parametrize("spell_id", ["divine_sacred_flame", "divine_flame_strike"])
async def test_radiant_bypasses_and_suppresses_next_turn(spell_fight, spell_id):
    ctx = spell_fight
    await prepare_absorb(ctx, spell_id)
    cast = await ally_cast(ctx)
    assert "absorbed" not in cast
    damage = cast["damage_result"]["damage"]
    state = await load_combat(ctx.userdata.combat_state.combat_id)
    assert damage == (14 if spell_id == "divine_sacred_flame" else 9)
    assert participant(state, "foe").hp_current == 70 - damage
    assert participant(state, "foe").radiant_suppression_pending
    ctx.userdata.combat_state = state
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        result = await _resolve_round(ctx)
    regen = next(e for p in result["packets"] for e in p.get("turn_start_effects", []) if e["effect"] == "regeneration")
    assert regen["suppressed"] and regen["causes"] == ["radiant"] and regen["healed"] == 0


async def test_ordinary_enemy_damage_with_veilrender_present(spell_fight):
    ctx = spell_fight
    state = ctx.userdata.combat_state
    state.participants.append(_enemy("other", 100))
    state.initiative_order.append("other")
    await prepare_absorb(ctx, targets=["other"])
    cast = await ally_cast(ctx)
    loaded = await load_combat(state.combat_id)
    assert "absorbed" not in cast
    assert participant(loaded, "other").hp_current == 100 - cast["damage_result"]["damage"] < 100
    assert participant(loaded, "foe").hp_current == 70
