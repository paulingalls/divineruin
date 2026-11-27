"""A second caster's hold on an already held target, checked at the phase receipt and saved state."""

import pytest
from acceptance._spell_hostile_condition_helpers import (
    DETECT,
    HOLD,
    STUN,
    add_player,
    cast_spell,
    defend,
    instance,
    play,
    receipt,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant


@pytest.mark.parametrize("same_phase", [True, False])
async def test_second_hold_on_a_held_target_keeps_the_first_casters_hold(spell_fight, same_phase):
    ctx = spell_fight
    player = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (HOLD,))
    foe = await set_foe(ctx)
    before = await saved_player(other)
    if same_phase:
        packets, held = await play(ctx, cast_spell(player, HOLD), cast_spell(other, HOLD))
    else:
        await play(ctx, cast_spell(player, HOLD), defend(other))
        packets, held = await play(ctx, defend(player), cast_spell(other, HOLD))
    cast = receipt(packets, other)
    assert participant(held, "foe").conditions == [instance("paralyzed", HOLD, player, "wis")]
    assert cast.get("condition_outcome") == "already_held" and foe.name in cast["narration_cue"]
    assert "save" not in cast and "condition_inflicted" not in cast
    second = await saved_player(other)
    assert second["concentration"] == {"spell_id": None}
    assert second["focus"]["current"] == before["focus"]["current"] - 3
    assert (await saved_player(player))["concentration"] == {"spell_id": HOLD}
    _, freed = await play(ctx, cast_spell(player, DETECT, None), defend(other))
    assert participant(freed, "foe").conditions == []


async def test_other_casters_stun_does_not_block_a_hold_or_a_stun_refresh(spell_fight):
    ctx = spell_fight
    player = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (STUN,))
    await set_foe(ctx, hp=70)
    await play(ctx, defend(player), cast_spell(other, STUN))
    packets, held = await play(ctx, cast_spell(player, HOLD), defend(other))
    ours = instance("paralyzed", HOLD, player, "wis")
    assert receipt(packets, player)["condition_inflicted"] == "paralyzed"
    assert participant(held, "foe").conditions == [instance("stunned", STUN, other, "con"), ours]
    # Power Word Stun holds no concentration, so another caster's stun refreshes as before.
    packets, saved = await play(ctx, cast_spell(player, STUN), defend(other))
    assert receipt(packets, player)["condition_inflicted"] == "stunned"
    assert ours in participant(saved, "foe").conditions
    assert (await saved_player(player))["concentration"] == {"spell_id": HOLD}
