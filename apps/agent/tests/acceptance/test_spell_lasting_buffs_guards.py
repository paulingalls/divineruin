"""Resource-preserving refusals at the spell declaration and activation boundaries."""

import json
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die
from acceptance._spell_hostile_condition_helpers import add_player, attack, cast_spell, play, set_foe
from acceptance._spell_hostile_condition_helpers import dev_db_pool as dev_db_pool
from acceptance.test_spell_bless_lifecycle import context, ooc_player, swing
from acceptance.test_spell_lasting_buffs import BEACON, PROTECTION, WARD, save_face
from acceptance.test_still_absorption import clock as clock
from acceptance.test_still_paradise_trap import paradise as paradise
from combat.test_spell_damage_lands import saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from livekit.agents import ToolError
from voice_condition_fixtures import participant

import combat_turn
import db
import db_mutations
from activate_tools import activate
from party_state import PartyState


@pytest.mark.parametrize("spell", [WARD, BEACON, PROTECTION, "divine_bless"])
@pytest.mark.parametrize("recipient", ["enemy", "missing", "dead"])
async def test_beneficial_spells_refuse_ineligible_recipients(spell_fight, spell, recipient):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    await set_foe(ctx)
    target = {"enemy": "foe", "missing": "missing", "dead": "dead"}[recipient]
    if recipient == "dead":
        target = await add_player(ctx, "warrior")
        state = ctx.userdata.combat_state
        actor = participant(state, target)
        actor.hp_current = 0
        actor.is_fallen = actor.is_dead = True
        await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    before = await saved_player(caster)
    with pytest.raises(ToolError, match=r"requires an ally|Unknown target"):
        await play(ctx, cast_spell(caster, spell, target))
    assert await saved_player(caster) == before


async def test_ward_requires_a_combat_turn(dev_db_pool):
    caster = await ooc_player(WARD)
    before = await saved_player(caster)
    with pytest.raises(ToolError, match="cast in combat with declare_phase"):
        await activate(context(caster), WARD)
    assert await saved_player(caster) == before


@pytest.mark.parametrize("combat", [False, True])
async def test_beacon_refuses_four_without_spending(spell_fight, combat):
    if combat:
        ctx = spell_fight
        caster = ctx.userdata.player_id
        targets = [caster, *[await add_player(ctx, "warrior") for _ in range(3)]]
        await set_foe(ctx)
        await play(ctx, cast_spell(caster, "divine_bless", caster))
    else:
        caster = await ooc_player(BEACON, "divine_bless")
        ctx = context(caster)
        targets = [caster, *[await ooc_player() for _ in range(3)]]
        for pid in targets[1:]:
            ctx.userdata.party.members.append(PartyState.solo(pid).primary)
        await activate(ctx, "divine_bless")
    before = [await saved_player(pid) for pid in targets]
    with pytest.raises(ToolError, match="at most 3"):
        if combat:
            ability = cast_spell(caster, BEACON)
            ability.targets = targets
            await play(ctx, ability)
        else:
            await activate(ctx, BEACON, target_ids=targets)
    assert [await saved_player(pid) for pid in targets] == before
    assert ctx.userdata.concentration.spell_id == "divine_bless"


async def test_protection_covers_still_arrival_and_dwell(paradise, clock):
    from acceptance.seeds import seed_known_spells
    from acceptance.test_still_absorption import HOUR, advance, background, charm
    from acceptance.test_still_paradise_trap import command, exploration

    walk, _, zone = paradise
    caster, guest = walk.players
    await seed_known_spells(walk.pool, caster, (PROTECTION,))
    await activate(context(caster), PROTECTION)
    with patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(19), _d20(5)]):
        arrival = await command(walk, "move_player", zone)
    assert not await charm(caster, zone)
    assert await charm(guest, zone)
    assert "Iona does not want to leave" in json.dumps(arrival["still"])

    await exploration(walk)
    async with background(walk) as tick:
        with patch("check_resolution.dice_roll", return_value=_d20(5)):
            await advance(clock, tick, HOUR)
        assert await charm(guest, zone)

        cast_ctx = context(caster)
        cast_ctx.userdata = walk.sd
        await activate(cast_ctx, PROTECTION, target_id=guest)
        with patch("check_resolution.dice_roll", side_effect=[_d20(5), _d20(19)]):
            await advance(clock, tick, HOUR)
        assert not await charm(guest, zone)


@pytest.mark.parametrize("spell", [WARD, PROTECTION])
async def test_held_hollow_attack_keeps_original_mode_and_damage(spell_fight, spell):
    from acceptance._spell_hostile_condition_helpers import reload

    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "warrior")
    foe = await set_foe(ctx, "hollow_mawling")
    state = ctx.userdata.combat_state
    target = participant(state, ally)
    target.hp_current = target.hp_max = 28
    target.ac = 18
    action = next(action for action in foe.action_pool if action["name"] == "Claw")
    action.update(damage="12d1", damage_type="fire")
    await db_mutations.save_combat_state(state.combat_id, state.to_dict())
    await (await db.get_pool()).execute(
        "UPDATE players SET data=jsonb_set(data,'{divine_favor}',$2::jsonb) WHERE player_id=$1",
        caster,
        '{"patron":"zhael","level":40,"max":100}',
    )
    await combat_turn.declare_phase(ctx, [cast_spell(caster, spell, ally), attack(foe.id, "Claw", ally)])
    with (
        patch("check_resolution.dice_roll", side_effect=[_d20(19), _d20(5)]),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(12)),
    ):
        offer = None
        for _ in range(4):
            async with ctx.userdata.fate_lock:
                packet = json.loads(await combat_turn.resolve_phase(ctx))
            if offer := packet.get("fate_offer"):
                break
    assert offer is not None
    state = await reload(ctx)
    assert participant(state, ally).hp_current == (await saved_player(ally))["hp"]["current"] == 28
    with patch("check_resolution.dice_roll", return_value=_d20(20)):
        async with ctx.userdata.fate_lock:
            resumed = json.loads(await activate(ctx, "zhael_fates_thread", offer_id=offer["offer_id"], keep="original"))
    result = swing(resumed["packets"], foe.id)
    expected = (19, True, 6) if spell == WARD else (5, False, 0)
    assert (result["roll"], result["hit"], result.get("damage", 0)) == expected
    assert (await saved_player(ally))["hp"]["current"] == 28 - expected[2]


@pytest.mark.parametrize(
    "spell, attribute, effect", [(BEACON, "wisdom", "resist"), (PROTECTION, "constitution", "hollowed")]
)
async def test_damage_break_removes_buff_without_touching_another_caster(spell_fight, spell, attribute, effect):
    ctx = spell_fight
    caster = ctx.userdata.player_id
    ally = await add_player(ctx, "cleric", ("divine_bless",))
    foe = await set_foe(ctx)
    await play(ctx, cast_spell(caster, spell, ally), cast_spell(ally, "divine_bless", caster))
    buffed = context(ally)
    buffed.userdata.combat_state = ctx.userdata.combat_state
    assert await save_face(buffed, attribute, effect) == 17
    packets, state = await play(ctx, attack(foe.id, "Short Sword", caster), faces=[17, 1])
    assert swing(packets, foe.id)["concentration_broken"] == spell
    buffed.userdata.combat_state = state
    assert await save_face(buffed, attribute, effect) == 5
    assert (await saved_player(ally))["concentration"]["spell_id"] == "divine_bless"
    assert any(c["type"] == "blessed" for c in participant(state, caster).conditions)
