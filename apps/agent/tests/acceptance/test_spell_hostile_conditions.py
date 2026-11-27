"""Hostile spell conditions through registered phase tools and committed combat state."""

import pytest
from acceptance._spell_hostile_condition_helpers import (
    HOLD,
    STUN,
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

import combat_turn
import spell_casting
from declaration_payloads import AbilityDecl


async def test_hold_person_rejects_beast_before_spending(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx, "grey_wolf")
    before = (await reload(ctx)).to_dict()
    row = await saved_player(player)
    with pytest.raises(ToolError, match="humanoid"):
        await combat_turn.declare_phase(ctx, [cast_spell(player, HOLD)])
    assert (await reload(ctx)).to_dict() == before
    assert await saved_player(player) == row


async def test_hold_person_rejects_two_enemy_targets_before_spending(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    await set_foe(ctx)
    await set_foe(ctx, foe_id="other_foe")
    before = (await reload(ctx)).to_dict()
    row = await saved_player(player)
    both = AbilityDecl(kind="ability", actor_id=player, action=HOLD, targets=["foe", "other_foe"], argument_type="")
    with pytest.raises(ToolError, match="one standing enemy"):
        await combat_turn.declare_phase(ctx, [both])
    assert (await reload(ctx)).to_dict() == before
    assert await saved_player(player) == row


@pytest.mark.parametrize("spell", [HOLD, STUN])
async def test_hostile_condition_spell_refused_outside_combat(spell_fight, spell):
    ctx = spell_fight
    player = ctx.userdata.player_id
    ctx.userdata.combat_state = None
    before = await saved_player(player)
    with pytest.raises(ToolError, match="combat"):
        await spell_casting._cast_spell_impl(ctx, spell, target_id="foe")
    assert await saved_player(player) == before


async def test_hold_person_skips_enemy_action_and_turns_melee_hit_into_crit(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    foe = await set_foe(ctx)
    enemy_attack = attack("foe", foe.action_pool[0]["name"], player)
    dagger = attack(player, participant(ctx.userdata.combat_state, player).action_pool[0]["name"], "foe")

    await play(ctx, defend(player), defend("foe"))
    control, control_state = await play(ctx, dagger, enemy_attack, face=13)
    assert participant(control_state, "foe").conditions == []
    await set_foe(ctx)

    before = await saved_player(player)
    packets, held = await play(ctx, cast_spell(player, HOLD), enemy_attack)
    cast = receipt(packets, player)
    assert any(p["actor_id"] == "foe" and "paralyzed" in p.get("reason", "") for p in packets)
    assert participant(held, player).hp_current == participant(control_state, player).hp_current
    assert cast["save"]["attribute"] == "wisdom" and not cast["save"]["success"]
    assert participant(held, "foe").conditions == [instance("paralyzed", HOLD, player, "wis")]
    assert (await saved_player(player))["focus"]["current"] == before["focus"]["current"] - 3

    packets, cleared = await play(ctx, dagger, face=13)
    assert participant(cleared, "foe").conditions == []
    assert participant(cleared, "foe").hp_current < participant(control_state, "foe").hp_current
    assert any(packet.get("critical") for packet in packets if packet["actor_id"] == player)
    assert not any(packet.get("critical") for packet in control if packet["actor_id"] == player)
    _, next_phase = await play(ctx, defend(player), enemy_attack, face=13)
    assert participant(next_phase, player).hp_current < participant(cleared, player).hp_current
