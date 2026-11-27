"""Concentration deadlines settle before the next declaration."""

from unittest.mock import patch

from acceptance._capstone_helpers import _d20
from acceptance._spell_hostile_condition_helpers import HOLD, add_player, attack, cast_spell, defend, play, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_spell_bless_lifecycle import BLESS, swing
from acceptance.test_spell_new_conditions import equip
from combat.test_spell_damage_lands import prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant
from weapon_fixtures import DAGGER


async def test_round_deadlines_release_bless_and_hold(spell_fight) -> None:
    ctx = spell_fight
    caster = ctx.userdata.player_id
    holder = await add_player(ctx, "mage", (HOLD,))
    second = await add_player(ctx, "cleric", (BLESS,))
    ally = await add_player(ctx, "warrior")
    control = await add_player(ctx, "warrior")
    await equip(ctx, ally, dict(DAGGER))
    await equip(ctx, control, dict(DAGGER))
    await set_foe(ctx, hp=500)
    await prepare_spell(ctx, BLESS)
    bless = cast_spell(caster, BLESS)
    bless.targets = [ally, holder]
    await play(ctx, bless, defend("foe"))
    await play(ctx, cast_spell(holder, HOLD, "foe"), cast_spell(second, BLESS, holder))
    for _ in range(3, 10):
        await play(ctx, defend(ally))
    for round_number, expected_bonus in ((10, 3), (11, 0)):
        assert ctx.userdata.combat_state.round_number == round_number
        with patch("condition_bonus.dice_roll", return_value=_d20(3)):
            packets, state = await play(
                ctx, attack(ally, DAGGER["name"], "foe"), attack(control, DAGGER["name"], "foe"), face=2
            )
        assert swing(packets, ally)["attack_total"] == swing(packets, control)["attack_total"] + expected_bonus
        assert (await saved_player(caster))["concentration"]["spell_id"] is None
        assert (await saved_player(holder))["concentration"]["spell_id"] == (HOLD if round_number == 10 else None)
        still_held = round_number == 10
        assert any(c["type"] == "paralyzed" for c in participant(state, "foe").conditions) == still_held
        assert [
            condition["sustaining_caster_ids"]
            for condition in participant(state, holder).conditions
            if condition["type"] == "blessed"
        ] == ([[second]] if still_held else [])


async def test_tsunami_has_six_rounds_while_a_longer_cast_survives(spell_fight) -> None:
    from acceptance._spell_hostile_condition_helpers import DETECT

    ctx = spell_fight
    caster = ctx.userdata.player_id
    other = await add_player(ctx, "mage", (DETECT,))
    await set_foe(ctx, hp=500)
    tsunami = "primal_tsunami"
    await prepare_spell(ctx, tsunami)
    await play(ctx, cast_spell(caster, tsunami, "foe"), cast_spell(other, DETECT, None), defend("foe"))
    for _ in range(2, 6):
        await play(ctx, defend("foe"))
    assert ctx.userdata.combat_state.round_number == 6
    assert (await saved_player(caster))["concentration"]["spell_id"] == tsunami
    await play(ctx, defend("foe"))
    assert ctx.userdata.combat_state.round_number == 7
    assert (await saved_player(caster))["concentration"]["spell_id"] is None
    assert (await saved_player(other))["concentration"]["spell_id"] == DETECT
