"""One-shot attack advantage and invisibility through registered phase tools."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20
from acceptance._spell_hostile_condition_helpers import (
    add_player,
    attack,
    cast_spell,
    defend,
    play,
    receipt,
    reload,
    set_foe,
)
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_spell_bless_lifecycle import context
from acceptance.test_spell_new_conditions import CROSSBOW, FIRE, equip
from combat.test_spell_damage_lands import minimum_roll, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant, spatial_record
from weapon_fixtures import DAGGER

import combat_turn
import db
import db_mutations
from activate_tools import activate
from check_payloads import SkillCheck
from check_tools import check

GUIDING = "divine_guiding_light"
INVISIBILITY = "arcane_invisibility"
MARK = "guiding_light_mark"
INVISIBLE = "invisible"
BOLT = "arcane_bolt"


def has(state, actor, kind):
    return any(condition["type"] == kind for condition in participant(state, actor).conditions)


def swing(packets, actor):
    return next(packet for packet in packets if packet["actor_id"] == actor and "hit" in packet)


async def mark_fight(ctx, ac=12):
    await set_foe(ctx, foe_id="control")
    await set_foe(ctx)
    ally = ctx.userdata.player_id
    caster = await add_player(ctx, "cleric", (GUIDING,))
    await equip(ctx, ally, DAGGER)
    state = ctx.userdata.combat_state
    participant(state, ally).initiative = 25
    for foe in ("foe", "control"):
        participant(state, foe).ac = ac
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    return caster, ally


async def mark(ctx, caster, foe="foe"):
    packets, state = await play(ctx, cast_spell(caster, GUIDING, foe))
    cast = receipt(packets, caster)
    assert "save" not in cast and "damage_result" not in cast
    assert participant(state, foe).hp_current == 100
    return state


def assert_attack(packets, actor, face, spell):
    roll = receipt(packets, actor)["damage_result"] if spell else swing(packets, actor)
    if spell:
        assert roll["attack_total"] == face + 6
    else:
        assert roll["roll"] == face
    assert roll["hit"] is (face == 17)


@pytest.mark.parametrize("spell", [False, True])
async def test_mark_changes_only_the_first_attack_after_reload(spell_fight, spell):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    second = await add_player(ctx, "mage", (BOLT,))
    participant(ctx.userdata.combat_state, second).initiative = 23
    await equip(ctx, second, DAGGER)

    def swing_at(actor, foe):
        return cast_spell(actor, BOLT, foe) if spell else attack(actor, DAGGER["name"], foe)

    packets, _ = await play(ctx, swing_at(ally, "control"), faces=[3, 17])
    assert_attack(packets, ally, 3, spell)
    await mark(ctx, caster)
    packets, state = await play(ctx, swing_at(ally, "foe"), swing_at(second, "foe"), faces=[3, 17, 3, 17])
    assert_attack(packets, ally, 17, spell)
    assert_attack(packets, second, 3, spell)
    assert not has(state, "foe", MARK)


async def test_missed_attack_spends_the_mark(spell_fight):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx, ac=24)
    participant(ctx.userdata.combat_state, caster).initiative = 30
    strike = attack(ally, DAGGER["name"], "foe")
    packets, state = await play(ctx, cast_spell(caster, GUIDING), strike, faces=[3, 7])
    rolled = swing(packets, ally)
    assert (rolled["roll"], rolled["hit"], rolled["damage"]) == (7, False, 0)
    assert not has(state, "foe", MARK)
    packets, _ = await play(ctx, strike, faces=[3, 17])
    assert swing(packets, ally)["roll"] == 3


@pytest.mark.parametrize("action", ["Short Sword", "Light Crossbow"])
async def test_invisible_ally_can_be_attacked_until_they_strike(spell_fight, action):
    ctx = spell_fight
    ally = await add_player(ctx, "mage")
    caster = ctx.userdata.player_id
    foe = await set_foe(ctx)
    await equip(ctx, ally, DAGGER)
    with pytest.raises(ToolError, match="declare_phase"):
        await activate(ctx, INVISIBILITY, target_id=ally)
    strike = attack(foe.id, action, ally)
    before = await saved_player(ally)
    packets, _ = await play(ctx, strike, faces=[17, 3])
    assert swing(packets, foe.id)["roll"] == 17
    packets, state = await play(ctx, cast_spell(caster, INVISIBILITY, ally), strike, faces=[17, 3])
    incoming = next(p for p in packets if p["actor_id"] == foe.id)
    assert incoming.get("roll") == 3, incoming
    assert has(state, ally, INVISIBLE)
    assert (await saved_player(ally)).get("flags") == before.get("flags")
    packets, state = await play(ctx, attack(ally, DAGGER["name"], foe.id), defend(foe.id), face=1)
    assert swing(packets, ally)["condition_removed"] == INVISIBLE
    assert not has(state, ally, INVISIBLE)
    packets, _ = await play(ctx, strike, faces=[17, 3])
    assert swing(packets, foe.id)["roll"] == 17


@pytest.mark.parametrize("queued", [False, True])
async def test_outline_refuses_invisibility_before_payment(spell_fight, queued):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    druid = await add_player(ctx, "druid", (FIRE,))
    ally = await add_player(ctx, "mage")
    await set_foe(ctx)
    state = ctx.userdata.combat_state
    participant(state, druid).initiative = 30
    spatial_record(state)["positions"][caster]["x"] = 40
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    extra_target = cast_spell(caster, INVISIBILITY, caster)
    extra_target.targets.append(ally)
    with pytest.raises(ToolError, match="at most 1"):
        await combat_turn.declare_phase(ctx, [extra_target])
    await play(ctx, cast_spell(caster, INVISIBILITY, caster))
    await (await db.get_pool()).execute(
        "UPDATE players SET data=jsonb_set(data,'{resonance,current}','0') WHERE player_id=$1", caster
    )
    ctx.userdata.member_state(caster).resonance.current = 0
    before = await saved_player(caster)
    outline = cast_spell(druid, FIRE, ally)
    invisible = cast_spell(caster, INVISIBILITY, ally)
    if queued:
        packets, state = await play(ctx, outline, invisible, face=1)
        refused = next(p for p in packets if p["actor_id"] == caster)
        assert not refused["resolved"] and "outline" in refused["reason"].lower()
    else:
        _, state = await play(ctx, outline, face=1)
        snapshot = state.to_dict()
        with pytest.raises(ToolError, match="outline"):
            await combat_turn.declare_phase(ctx, [invisible])
        with pytest.raises(ToolError, match="outline"):
            await activate(ctx, INVISIBILITY, target_id=ally)
        assert (await reload(ctx)).to_dict() == snapshot
    assert has(state, ally, "outlined") and not has(state, ally, INVISIBLE)
    assert has(state, caster, INVISIBLE)
    after = await saved_player(caster)
    for key in ("focus", "resonance", "concentration"):
        assert after[key] == before[key]


async def test_faerie_fire_reveals_only_failed_save_recipients(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    druid = await add_player(ctx, "druid", (FIRE,))
    second = await add_player(ctx, "mage", (INVISIBILITY,))
    ally = await add_player(ctx, "mage")
    control = await add_player(ctx, "mage")
    await set_foe(ctx)
    state = ctx.userdata.combat_state
    positions = spatial_record(state)["positions"]
    positions["foe"]["x"] = 40
    positions[ally]["x"] = positions[control]["x"] = 40
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await play(ctx, cast_spell(caster, INVISIBILITY, ally), cast_spell(second, INVISIBILITY, control))
    packets, state = await play(ctx, cast_spell(druid, FIRE, ally), faces=[1, 20, 20])
    assert receipt(packets, druid)["condition_targets"] == [ally]
    assert has(state, ally, "outlined") and not has(state, ally, INVISIBLE)
    assert has(state, control, INVISIBLE) and not has(state, control, "outlined")
    packets, _ = await play(ctx, attack("foe", "Short Sword", ally), faces=[3, 17])
    assert swing(packets, "foe")["roll"] == 17


async def skill_face(ctx, skill):
    payload = SkillCheck(
        kind="skill",
        synergy_context="none",
        skill=skill,
        difficulty="very_hard",
        context_description="Slip behind the barricade",
        hearing_only=False,
    )
    with patch("check_resolution.dice_roll", side_effect=[_d20(3), _d20(17)]):
        return json.loads(await check(ctx, payload))["roll"]


async def test_invisibility_changes_stealth_and_only_hostile_casts_break_it(spell_fight):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "cleric", (GUIDING, "divine_divine_ward", "divine_sacred_word", "divine_mend"))
    await set_foe(ctx)
    check_ctx = context(ally)
    check_ctx.userdata.combat_state = await reload(ctx)
    await activate(check_ctx, "divine_sacred_word")
    assert await skill_face(check_ctx, "stealth") == 3
    _, check_ctx.userdata.combat_state = await play(ctx, cast_spell(caster, INVISIBILITY, ally))
    assert await skill_face(check_ctx, "stealth") == 17
    assert await skill_face(check_ctx, "acrobatics") == 3
    await activate(check_ctx, "divine_mend")
    assert await skill_face(check_ctx, "stealth") == 17
    before = await saved_player(ally)
    with pytest.raises(ToolError, match="declare_phase"):
        await activate(check_ctx, "divine_sacred_word")
    assert await saved_player(ally) == before
    _, state = await play(ctx, cast_spell(ally, "divine_divine_ward", ally))
    assert has(state, ally, INVISIBLE)
    packets, state = await play(ctx, cast_spell(ally, GUIDING))
    assert receipt(packets, ally)["condition_removed"] == INVISIBLE
    assert not has(state, ally, INVISIBLE)


@pytest.mark.parametrize("turn", ["marked", "different", "omitted"])
async def test_unused_mark_expires_at_its_casters_next_turn_end(spell_fight, turn):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    if turn == "different":
        other = await add_player(ctx, "cleric", (GUIDING,))
        await set_foe(ctx, foe_id="spare")
        other_ally = await add_player(ctx, "mage", (BOLT,))
        participant(ctx.userdata.combat_state, other_ally).initiative = 23
    state = ctx.userdata.combat_state
    participant(state, caster).initiative = 30
    await equip(ctx, caster, CROSSBOW)
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    if turn == "different":
        _, state = await play(ctx, cast_spell(caster, GUIDING), cast_spell(other, GUIDING, "spare"))
        assert has(state, "spare", MARK)
    else:
        state = await mark(ctx, caster)
    assert has(state, "foe", MARK)
    followup = attack(ally, DAGGER["name"], "foe")
    if turn == "marked":
        packets, state = await play(ctx, attack(caster, CROSSBOW["name"], "foe"), followup, faces=[3, 17, 3, 17])
        assert swing(packets, caster)["roll"] == 17
    elif turn == "different":
        packets, state = await play(
            ctx,
            attack(caster, CROSSBOW["name"], "control"),
            followup,
            cast_spell(other_ally, BOLT, "spare"),
            faces=[3, 3, 5, 17, 1],
        )
        assert receipt(packets, other_ally)["damage_result"]["attack_total"] == 23
    else:
        packets, state = await play(ctx, followup, faces=[3, 17])
    assert swing(packets, ally)["roll"] == 3
    assert not has(state, "foe", MARK)


async def test_area_cast_leaves_mark_and_breaks_its_invisible_caster(spell_fight):
    ctx = spell_fight
    caster, ally = await mark_fight(ctx)
    mage = await add_player(ctx, "mage", (INVISIBILITY,))
    await equip(ctx, caster, CROSSBOW)
    state = ctx.userdata.combat_state
    participant(state, caster).initiative = 30
    for foe in ("foe", "control"):
        spatial_record(state)["positions"][foe]["x"] = 30
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await play(ctx, cast_spell(mage, INVISIBILITY, ally))
    with patch("dice.roll", side_effect=minimum_roll):
        packets, state = await play(ctx, cast_spell(caster, GUIDING), cast_spell(ally, "arcane_fireball"), face=1)
    assert receipt(packets, ally)["condition_removed"] == INVISIBLE
    results = {result["target_id"]: result for result in receipt(packets, ally)["damage_results"]}
    marked, control = results["foe"], results["control"]
    assert marked["save"] == control["save"] and marked["damage"] == control["damage"]
    assert not has(state, ally, INVISIBLE)
    assert has(state, "foe", MARK)
    packets, state = await play(ctx, attack(caster, CROSSBOW["name"], "foe"), faces=[3, 17])
    assert swing(packets, caster)["roll"] == 17
    assert not has(state, "foe", MARK)
