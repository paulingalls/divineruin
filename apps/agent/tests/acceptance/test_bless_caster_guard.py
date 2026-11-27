"""Caster-specific Bless release across live combat and persisted player rows."""

from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance._spell_hostile_condition_helpers import (
    add_player,
    attack,
    cast_spell,
    defend,
    play,
    reload,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_spell_bless_lifecycle import BLESS, DETECT, context, ooc_player, save_total
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents.llm import ToolError
from voice_condition_fixtures import participant

import concentration_break
import conditions
import db_mutations_conditions
from activate_tools import activate
from party_state import PartyState


def bless_owners(conditions):
    return [c.get("sustaining_caster_ids") for c in conditions if c["type"] == "blessed"]


async def break_on_damage(ctx, caster, *, face=1):
    with patch("check_resolution.dice_roll", return_value=_d20(face)):
        return await concentration_break.break_concentration_on_damage(
            ctx.userdata, 20, False, damaged_player_id=caster
        )


@pytest.mark.parametrize("cause", ["damage", "incapacitation", "replacement"])
async def test_exclusive_bless_ends_without_touching_other_caster(spell_fight, cause):
    ctx = spell_fight
    a = ctx.userdata.player_id
    b = await add_player(ctx, "cleric", (BLESS,))
    foe = await set_foe(ctx, "cult_leader")
    await play(ctx, cast_spell(a, BLESS, b), cast_spell(b, BLESS, a), defend(foe.id))

    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        assert (
            await concentration_break.break_concentration_on_damage(ctx.userdata, 20, False, damaged_player_id=a)
            is None
        )
    if cause == "replacement":
        await play(ctx, cast_spell(a, BLESS, a), defend(b), defend("foe"))
    else:
        if cause == "incapacitation":
            blow, faces = cast_spell(foe.id, "Hold Person", a), [1] * 8
        else:
            blow, faces = attack(foe.id, foe.action_pool[0]["name"], a), [19, 1, *([1] * 6)]
        packets, _ = await play(ctx, defend(a), defend(b), blow, faces=faces)
        hit = next(packet for packet in packets if packet["actor_id"] == foe.id)
        if cause == "incapacitation":
            assert hit["condition_inflicted"] == "paralyzed"
        else:
            assert hit["damage"] > 0 and hit["concentration_broken"] == BLESS
        assert (await saved_player(a))["concentration"] == {"spell_id": None}

    state = await reload(ctx)
    assert bless_owners(participant(state, b).conditions) == []
    remaining = sorted([a, b]) if cause == "replacement" else [b]
    assert bless_owners(participant(state, a).conditions) == [remaining]


async def test_activate_cannot_replace_combat_bless(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await set_foe(ctx)
    await play(ctx, cast_spell(caster, BLESS, caster), defend("foe"))
    focus = (await saved_player(caster))["focus"]
    with pytest.raises(ToolError, match="declare_phase"):
        await activate(ctx, DETECT)
    state = await reload(ctx)
    assert (await saved_player(caster))["focus"] == focus
    assert ctx.userdata.concentration.spell_id == BLESS
    assert bless_owners(participant(state, caster).conditions) == [[caster]]


@pytest.mark.parametrize("reverse", [False, True])
async def test_persisted_shared_bless_last_caster_removes_die(dev_db_pool, reverse):
    a, b, ally, control = await ooc_player(BLESS), await ooc_player(BLESS), await ooc_player(), await ooc_player()
    contexts = {caster: context(caster) for caster in (a, b)}
    for ctx in contexts.values():
        ctx.userdata.party.members.append(PartyState.solo(ally).primary)
        await activate(ctx, BLESS, target_id=ally)

    wounded = conditions.apply_condition([], "wounded", source="battle")
    for pid in (ally, control):
        existing = (await saved_player(pid)).get("conditions") or []
        await db_mutations_conditions.save_player_conditions(pid, existing + wounded)
    baseline = await save_total(control)
    assert await save_total(ally) == baseline + 3
    first, last = (b, a) if reverse else (a, b)
    assert (await break_on_damage(contexts[first], first)) == BLESS
    assert bless_owners((await saved_player(ally))["conditions"]) == [[last]]
    assert await save_total(ally) == baseline + 3
    assert (await break_on_damage(contexts[last], last)) == BLESS
    assert (await saved_player(ally))["conditions"] == wounded
    assert await save_total(ally) == baseline


async def test_ooc_concentration_save_reads_bless_and_exhaustion(dev_db_pool):
    caster = await ooc_player(BLESS)
    ctx = context(caster)
    await activate(ctx, BLESS)
    buffs = (await saved_player(caster))["conditions"]
    exhausted = conditions.apply_condition(conditions.apply_condition([], "exhausted"), "exhausted")
    await db_mutations_conditions.save_player_conditions(caster, buffs + exhausted)

    with patch("condition_bonus.dice_roll", return_value=_d20(3)):
        assert await break_on_damage(ctx, caster, face=8) is None
        assert await break_on_damage(ctx, caster, face=6) == BLESS
    assert (await saved_player(caster))["conditions"] == exhausted


async def test_combat_break_releases_prior_recipient_outside_roster(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    outsider = await ooc_player()
    state = ctx.userdata.combat_state
    ctx.userdata.combat_state = None
    ctx.userdata.party.members.append(PartyState.solo(outsider).primary)
    await activate(ctx, BLESS, target_ids=[caster, outsider])
    assert bless_owners((await saved_player(outsider))["conditions"]) == [[caster]]
    caster_buffs = (await saved_player(caster))["conditions"]
    participant(state, caster).conditions = caster_buffs
    ctx.userdata.party.members.pop()
    ctx.userdata.combat_state = state
    foe = await set_foe(ctx, "cult_leader")
    await play(ctx, defend(caster), attack(foe.id, foe.action_pool[0]["name"], caster), faces=[19, 1])
    assert (await saved_player(caster))["concentration"] == {"spell_id": None}
    assert (await saved_player(outsider))["conditions"] == []
    assert (await saved_player(caster))["conditions"] == caster_buffs
    assert bless_owners(participant(await reload(ctx), caster).conditions) == []
