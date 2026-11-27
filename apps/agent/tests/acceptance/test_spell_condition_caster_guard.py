"""Silent condition outcomes checked at the phase receipt and persisted-state boundary."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _resolve_round
from acceptance._spell_hostile_condition_helpers import (
    DETECT,
    HOLD,
    STUN,
    add_player,
    attack,
    cast_spell,
    defend,
    instance,
    play,
    receipt,
    reload,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant
from weapon_fixtures import DAGGER

import choir_encounter
import combat_end
import combat_turn
import db
from activate_tools import _activate_impl, activate


async def test_successful_wisdom_save_prevents_paralysis(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx)
    _, control = await play(ctx, defend(player), defend("foe"), face=20)
    packets, saved = await play(ctx, cast_spell(player, HOLD), defend("foe"), face=20)
    cast = receipt(packets, player)
    assert cast["save"]["success"]
    assert cast.get("condition_outcome") == "resisted"
    assert participant(saved, "foe").conditions == participant(control, "foe").conditions == []


@pytest.mark.parametrize("hp", [70, 75, 76, 80])
async def test_stun_ceiling_spends_focus_and_keeps_failure_private(spell_fight, hp):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx, hp=hp)
    before = await saved_player(player)
    _, control = await play(ctx, defend(player), defend("foe"))
    assert (await saved_player(player))["focus"] == before["focus"]
    await combat_turn.declare_phase(ctx, [cast_spell(player, STUN), defend("foe")])
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        first = json.loads(await combat_turn.resolve_phase(ctx))
    saved = await reload(ctx)
    cast = receipt(first["packets"], player)
    assert (await saved_player(player))["focus"]["current"] == before["focus"]["current"] - 7
    assert participant(saved, "foe").hp_current == participant(control, "foe").hp_current == hp
    assert "save" not in cast
    if hp <= 75:
        assert participant(saved, "foe").conditions == [instance("stunned", STUN, player, "con")]
    else:
        assert participant(saved, "foe").conditions == participant(control, "foe").conditions == []
        assert cast["condition_outcome"] == "failed_unknown_to_caster"
        assert "they stop" not in cast["narration_cue"].lower()


async def test_stunned_target_clears_on_its_own_constitution_save(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    foe = await set_foe(ctx, hp=70)
    foe.attributes.update(wisdom=4, constitution=14)
    retaliation = attack("foe", foe.action_pool[0]["name"], player)
    packets, saved = await play(ctx, cast_spell(player, STUN), retaliation)
    assert "save" not in receipt(packets, player)
    assert any(p["actor_id"] == "foe" and "stunned" in p.get("reason", "") for p in packets)
    held = [instance("stunned", STUN, player, "con")]
    assert participant(saved, "foe").conditions == held
    _, saved = await play(ctx, defend(player), face=7)
    assert participant(saved, "foe").conditions == held
    _, saved = await play(ctx, defend(player), face=8)
    assert participant(saved, "foe").conditions == []
    packets, _ = await play(ctx, defend(player), retaliation, face=15)
    assert any(p["actor_id"] == "foe" and p.get("hit") for p in packets)


@pytest.mark.parametrize("replacement", [DETECT, HOLD])
async def test_replacement_frees_only_the_old_casters_target(spell_fight, replacement):
    ctx = spell_fight
    player = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (HOLD,))
    await set_foe(ctx)
    await set_foe(ctx, foe_id="other_foe")
    _, held = await play(ctx, cast_spell(player, HOLD), cast_spell(other, HOLD, "other_foe"))
    assert participant(held, "foe").conditions == [instance("paralyzed", HOLD, player, "wis")]
    second_hold = [instance("paralyzed", HOLD, other, "wis")]
    assert participant(held, "other_foe").conditions == second_hold

    before = await saved_player(player)
    # A fresh Hold Person can be resisted. The other target's wrap save still fails.
    packets, saved = await play(
        ctx,
        cast_spell(player, replacement, "foe" if replacement == HOLD else None),
        defend(other),
        faces=[20, 1, 1] if replacement == HOLD else None,
    )
    assert participant(saved, "foe").conditions == []
    assert participant(saved, "other_foe").conditions == second_hold
    if replacement == HOLD:
        assert receipt(packets, player)["condition_outcome"] == "resisted"
    after = await saved_player(player)
    assert after["concentration"] == {"spell_id": replacement}
    assert after["focus"]["current"] == before["focus"]["current"] - (3 if replacement == HOLD else 1)
    assert (await saved_player(other))["concentration"] == {"spell_id": HOLD}


async def test_activate_cannot_replace_a_live_combat_hold(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx)
    # The same activation in combat is legal when the mage holds no hostile condition.
    await _activate_impl(ctx, DETECT)
    assert (await saved_player(player))["concentration"] == {"spell_id": DETECT}
    await _activate_impl(ctx, DETECT)
    await play(ctx, cast_spell(player, HOLD))
    await _activate_impl(ctx, "arcane_prestidigitation")
    before = await saved_player(player)
    with pytest.raises(ToolError, match="declare_phase"):
        await _activate_impl(ctx, DETECT)
    saved = await reload(ctx)
    assert participant(saved, "foe").conditions == [instance("paralyzed", HOLD, player, "wis")]
    assert await saved_player(player) == before

    # Ending combat drops the combat row while concentration remains on the character.
    await combat_end.end_combat(ctx, "fled")
    assert not ctx.userdata.in_combat
    assert (await saved_player(player))["concentration"] == {"spell_id": HOLD}
    await _activate_impl(ctx, DETECT)
    assert (await saved_player(player))["concentration"] == {"spell_id": DETECT}


@pytest.mark.parametrize("cause", ["damage_fail", "damage_pass", "incapacitation"])
async def test_break_keeps_other_casters_hold_and_own_independent_stun(spell_fight, cause):
    ctx = spell_fight
    player = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (HOLD,))
    await set_foe(ctx)
    await set_foe(ctx, foe_id="other_foe")
    await set_foe(ctx, hp=70, foe_id="stunned_foe")
    assailant = await set_foe(ctx, "cult_leader", foe_id="assailant")
    await play(ctx, cast_spell(player, STUN, "stunned_foe"), defend(other))
    _, held = await play(ctx, cast_spell(player, HOLD), cast_spell(other, HOLD, "other_foe"))
    ours = [instance("paralyzed", HOLD, player, "wis")]
    theirs = [instance("paralyzed", HOLD, other, "wis")]
    stunned = [instance("stunned", STUN, player, "con")]
    assert participant(held, "foe").conditions == ours
    assert participant(held, "other_foe").conditions == theirs
    assert participant(held, "stunned_foe").conditions == stunned

    if cause == "incapacitation":
        blow = cast_spell(assailant.id, "Hold Person", player)
        faces = [1] * 8
    else:
        blow = attack(assailant.id, assailant.action_pool[0]["name"], player)
        faces = [19, 19 if cause == "damage_pass" else 1, *([1] * 6)]
    packets, saved = await play(ctx, defend(player), defend(other), blow, faces=faces)
    keeps = cause == "damage_pass"
    attack_packet = next(p for p in packets if p["actor_id"] == assailant.id)
    if cause == "incapacitation":
        assert attack_packet["condition_inflicted"] == "paralyzed"
    else:
        assert attack_packet["damage"] > 0
        assert attack_packet.get("concentration_broken") == (None if keeps else HOLD)
    assert participant(saved, "foe").conditions == (ours if keeps else [])
    assert participant(saved, "other_foe").conditions == theirs
    assert participant(saved, "stunned_foe").conditions == stunned
    assert (await saved_player(player)).get("concentration") == {"spell_id": HOLD if keeps else None}
    assert (await saved_player(other))["concentration"] == {"spell_id": HOLD}


async def test_weapon_stun_refresh_discards_spell_clearing_save(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    warrior = await add_player(ctx, "warrior")
    fighter = participant(ctx.userdata.combat_state, warrior)
    fighter.action_pool = [dict(DAGGER)]
    await set_foe(ctx, hp=70)
    await play(ctx, cast_spell(player, STUN), defend(warrior))
    await combat_turn.declare_phase(ctx, [defend(player), attack(warrior, DAGGER["name"], "foe", "shield_bash")])
    with patch("check_resolution.dice_roll", side_effect=[_d20(15), _d20(1)]):
        first = json.loads(await combat_turn.resolve_phase(ctx))
    hit = next(p for p in first["packets"] if p["actor_id"] == warrior)
    assert hit["condition_inflicted"] == "stunned"
    updated = participant(await reload(ctx), "foe").conditions
    assert len(updated) == 1
    assert updated[0]["duration"] == 1 and updated[0]["source"] != STUN
    assert "tick_save" not in updated[0]
    assert "originating_participant_id" not in updated[0]
    await _resolve_round(ctx)
    assert participant(await reload(ctx), "foe").conditions == []


@pytest.mark.parametrize("face", [1, 20])
async def test_held_initial_save_resumes_after_reload_with_one_debit(spell_fight, face):
    ctx = spell_fight
    session = ctx.userdata
    player = session.player_id
    await set_foe(ctx)
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
        player,
        '{"patron":"zhael","level":40,"max":100}',
    )
    before = await saved_player(player)
    await combat_turn.declare_phase(ctx, [cast_spell(player, HOLD), defend("foe")])
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        async with session.fate_lock:
            offered = json.loads(await combat_turn.resolve_phase(ctx))["fate_offer"]
    saved = await reload(ctx)
    assert offered["roller_id"] == "foe" and offered["roll_kind"] == "save"
    assert participant(saved, "foe").conditions == []
    assert (await saved_player(player))["focus"]["current"] == before["focus"]["current"] - 3

    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        async with session.fate_lock:
            kept = json.loads(await activate(ctx, "zhael_fates_thread", offer_id=offered["offer_id"], keep="original"))
        await _resolve_round(ctx)
    cast = receipt(kept["packets"], player)
    assert cast["save"]["roll"] == face
    expected = [instance("paralyzed", HOLD, player, "wis")] if face == 1 else []
    assert participant(await reload(ctx), "foe").conditions == expected
    assert (await saved_player(player))["focus"]["current"] == before["focus"]["current"] - 3


async def test_absorbed_stun_has_no_landed_condition(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    target = await set_foe(ctx, "hollow_veilrender", hp=50)
    target.hp_max = 100
    await combat_turn.declare_phase(ctx, [cast_spell(player, STUN), defend("foe")])
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        first = json.loads(await combat_turn.resolve_phase(ctx))
    packets, saved = first["packets"], await reload(ctx)
    cast = receipt(packets, player)
    assert cast["absorbed"][0]["target_id"] == target.id
    assert "condition_inflicted" not in cast and "they stop" not in cast["narration_cue"].lower()
    actual = participant(saved, target.id)
    assert actual.conditions == [] and actual.hp_current == cast["absorbed"][0]["hp_current"] == 71


async def test_fallen_target_revalidated_after_an_earlier_ally_attack(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (STUN,))
    await set_foe(ctx, hp=1)
    await set_foe(ctx, foe_id="survivor")
    before = await saved_player(other)
    blade = participant(ctx.userdata.combat_state, player).action_pool[0]["name"]
    packets, saved = await play(ctx, attack(player, blade, "foe"), cast_spell(other, STUN), face=18)
    cast = receipt(packets, other)
    fallen = participant(saved, "foe")
    assert fallen.is_fallen and fallen.conditions == []
    assert cast.get("condition_outcome") == "ineligible_target"
    assert (await saved_player(other))["focus"]["current"] == before["focus"]["current"] - 7


async def test_redirected_stun_checks_the_effective_recipient(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx, "hollow_choir", hp=70)
    state = ctx.userdata.combat_state
    participant(state, player).hp_current = 28
    choir_encounter.initialize(state)
    state.choir_encounter["phase"] = "exposed"
    await combat_turn.declare_phase(ctx, [cast_spell(player, STUN), defend("foe")])
    with patch("check_resolution.dice_roll", return_value=_d20(1)):
        first = json.loads(await combat_turn.resolve_phase(ctx))
    cast = receipt(first["packets"], player)
    saved = await reload(ctx)
    assert cast["target_id"] == player
    assert cast.get("condition_outcome") == "ineligible_target"
    assert participant(saved, player).conditions == participant(saved, "foe").conditions == []
