"""Regenerate through registered spell and combat commands."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from _spell_heal_fixtures import REGENERATE
from _spell_heal_fixtures import spell_heal_walk as spell_heal_walk
from _zhael_fate_fixtures import game_tools
from acceptance._capstone_helpers import _d20
from sample_fixtures import published_payloads
from test_spell_heal_landing import heal_die, receipt

import db_mutations
import spells
from combat_turn import resolve_phase
from conditions import apply_condition
from db_mutations_concentration import update_player_concentration


def regeneration(actor):
    return [c for c in actor.conditions if c["type"] == "regenerating"]


async def cast_in_combat(healer, *, hp=10, maximum=40, state=None, ally: str | None = None) -> str:
    if state is None:
        ally = await healer.add_player(hp=hp, maximum=maximum)
        state = await healer.fight()
    assert ally is not None
    state.get_participant(ally).initiative = state.get_participant(healer.player).initiative + 1
    with heal_die(19) as roll:
        cast = await healer.cast(REGENERATE, targets=[ally], combat=True)
    current = min(hp + 19, maximum)
    assert cast["healing_results"] == [receipt(ally, current - hp, current, rolled=19, modifier=0, maximum=maximum)]
    assert [c.args[0] for c in roll.call_args_list] == ["4d8+15"]
    saved = await healer.checkpoint()
    assert regeneration(saved.get_participant(ally)) == [
        {"type": "regenerating", "source": healer.player, "duration": None, "stacks": 1, "ticks_remaining": 600}
    ]
    return ally


async def declare_defend(healer, *actors):
    await healer.command("declare_phase", {"declarations": [{"kind": "defend", "actor_id": a} for a in actors]})


def effects(packets):
    return [effect for packet in packets for effect in packet.get("turn_start_effects", [])]


async def set_hp(healer, ally, hp):
    target = healer.fight_state.get_participant(ally)
    target.hp_current = hp
    await db_mutations.update_player_hp(ally, hp)
    await healer.save()


async def test_recipient_turns_tick_once_across_checkpoint_reloads_and_omitted_declarations(healer):
    await healer.prepare(REGENERATE)
    ally = await cast_in_combat(healer)
    assert (await healer.focus()) == 30 - spells.get_spell(REGENERATE).focus_cost
    await set_hp(healer, ally, 10)
    for elapsed in range(1, 4):
        healer.sd.combat_state = await healer.checkpoint()
        turns = [healer.player] if elapsed == 2 else [healer.player, ally]
        await declare_defend(healer, *turns)
        packets = await healer.wrap()
        assert effects(packets) == [
            {
                "name": "Regenerating",
                "source_id": healer.player,
                "target_id": ally,
                "healed": 1,
                "hp_current": 10 + elapsed,
                "hp_max": 40,
            }
        ]
        assert (await healer.read(ally))["hp"]["current"] == 10 + elapsed
        saved = (await healer.checkpoint()).get_participant(ally)
        assert saved.hp_current == 10 + elapsed
        assert regeneration(saved)[0]["ticks_remaining"] == 600 - elapsed
    with heal_die(19):
        await healer.cast(REGENERATE, targets=[ally], combat=True)
    conditions = regeneration((await healer.checkpoint()).get_participant(ally))
    assert len(conditions) == 1 and conditions[0]["ticks_remaining"] == 600


@pytest.mark.parametrize("kaelen,maximum", [(False, 40), (True, 45)])
async def test_exploration_resolves_the_surge_and_hour(healer, kaelen, maximum):
    await healer.prepare(REGENERATE)
    ally = await healer.add_player(hp=10, maximum=40)
    if kaelen:
        await healer.patch_row(ally, divine_favor={"patron": "kaelen", "level": 40, "max": 100})
    with heal_die(19) as roll:
        cast = await healer.cast(REGENERATE, targets=[ally])
    assert cast["healing_results"] == [receipt(ally, maximum - 10, maximum, rolled=19, modifier=0, maximum=maximum)]
    assert roll.call_args.args[0] == "4d8+15"
    assert roll.call_count == 1
    assert (await healer.focus()) == 30 - spells.get_spell(REGENERATE).focus_cost
    row = await healer.read(ally)
    assert row["hp"] == {"current": maximum, "max": 40}
    assert not any(c["type"] == "regenerating" for c in row.get("conditions", []))
    assert {"type": "hp_changed", "current": maximum, "max": maximum} in published_payloads(healer.sd.room)


@pytest.mark.parametrize("outcome", ["victory", "fled", "defeat"])
async def test_combat_end_settles_regeneration_before_life_settlement(healer, outcome):
    await healer.prepare(REGENERATE)
    ally = await healer.add_player(hp=10, maximum=40)
    unmarked = await healer.add_player(hp=8, maximum=40)
    await healer.patch(hp={"current": 10, "max": 40})
    state = await healer.fight()
    recipient = healer.player if outcome == "defeat" else ally
    if recipient == healer.player:
        with heal_die(19):
            await healer.cast(REGENERATE, targets=[recipient], combat=True)
    else:
        await cast_in_combat(healer, state=state, ally=ally)
    if outcome == "victory":
        foe = healer.fight_state.get_participant("foe")
        foe.hp_current, foe.is_fallen = 0, True
        await declare_defend(healer, healer.player)
        await healer.command("resolve_phase", {})
    else:
        await healer.register_end()

    saved = healer.fight_state
    saved.get_participant(recipient).is_fallen = True
    await set_hp(healer, recipient, 0)
    if outcome == "victory":
        result = await healer.command("resolve_phase", {})
    else:
        result = await healer.command("end_combat", {"outcome": outcome})
    assert result["outcome"] == outcome
    assert healer.sd.combat_state is None
    assert await db_mutations.load_combat_state(saved.combat_id) is None
    row = await healer.read(recipient)
    assert row["hp"]["current"] == 40
    assert row["location_id"] == "millhaven_inn"
    assert not any(c["type"] == "regenerating" for c in row.get("conditions", []))
    assert (await healer.read(unmarked))["hp"]["current"] == 8
    sends = healer.sd.room.local_participant.publish_data.call_args_list
    payloads = published_payloads(healer.sd.room)
    hp_push = {"type": "hp_changed", "current": 40, "max": 40}
    assert [
        call.kwargs["destination_identities"]
        for call, payload in zip(sends, payloads, strict=True)
        if payload == hp_push
    ] == [[recipient]]


async def test_tick_spends_budget_at_effective_max_and_expires(healer, mock_combat_agent_factory):
    await healer.prepare(REGENERATE)
    ally = await healer.add_player(hp=10, maximum=40)
    await healer.patch_row(ally, divine_favor={"patron": "kaelen", "level": 40, "max": 100})
    await healer.enter(mock_combat_agent_factory)
    await cast_in_combat(healer, state=healer.fight_state, ally=ally, maximum=45)
    regeneration(healer.fight_state.get_participant(ally))[0]["ticks_remaining"] = 2
    await set_hp(healer, ally, 44)
    for healing in ([1], [0], []):
        await declare_defend(healer, healer.player)
        ticks = effects(await healer.wrap())
        assert [e["healed"] for e in ticks] == healing
        assert all(e["hp_current"] == e["hp_max"] == 45 for e in ticks)
        assert (await healer.read(ally))["hp"] == {"current": 45, "max": 40}
    assert not regeneration((await healer.checkpoint()).get_participant(ally))


@pytest.mark.parametrize("kind", ["player", "companion", "dead", "failed_saves"])
async def test_only_savable_fallers_regenerate(healer, kind):
    await healer.prepare(REGENERATE)
    if kind == "companion":
        state = await healer.fight(companion=True)
        ally = await cast_in_combat(healer, state=state, ally="companion", hp=3, maximum=20)
    else:
        ally = await cast_in_combat(healer)
    target = healer.fight_state.get_participant(ally)
    target.hp_current = 0
    target.is_fallen = True
    target.is_dead = kind == "dead"
    target.death_save_failures = 3 if kind == "failed_saves" else 1
    target.death_save_successes = 1
    if kind != "companion":
        await db_mutations.update_player_hp(ally, 0)
    await healer.save()

    await declare_defend(healer, healer.player)
    ticks = effects((await healer.command("resolve_phase", {}))["packets"])
    wrapped = await healer.command("resolve_phase", {})
    assert ally not in wrapped["death_saves_due"]
    saved = (await healer.checkpoint()).get_participant(ally)
    if kind in ("dead", "failed_saves"):
        assert not ticks and saved.is_fallen and saved.hp_current == 0
        assert regeneration(saved)[0]["ticks_remaining"] == 600
    else:
        assert ticks[0]["target_id"] == ally and ticks[0]["healed"] == 1
        assert saved.hp_current == 1 and not saved.is_fallen
        assert saved.death_save_failures == saved.death_save_successes == 0
    if kind != "companion":
        assert (await healer.read(ally))["hp"]["current"] == saved.hp_current


@pytest.mark.parametrize("hp,damage,expected", [(10, 4, 7), (1, 4, 1), (1, 50, 0)])
async def test_regeneration_follows_mawling_damage_and_its_held_save(healer, hp, damage, expected):
    await healer.prepare(REGENERATE)
    ally = await cast_in_combat(healer)
    state = healer.fight_state
    victim, mawling = state.get_participant(ally), state.get_participant("foe")
    victim.conditions = apply_condition(victim.conditions, "grappled", source=mawling.id)
    mawling.creature_id = "hollow_mawling"
    mawling.turn_start_damage = {"trigger": "grappled_by_source", "damage": "1d6", "damage_type": "necrotic"}
    if hp == 10:
        await healer.patch(divine_favor={"patron": "zhael", "level": 40, "max": 100})
        healer.sd.party.primary.patron_id = "zhael"
        healer.sd.member_state(ally).concentration.spell_id = "divine_bless"
        await update_player_concentration(ally, "divine_bless")
    await set_hp(healer, ally, hp)

    await declare_defend(healer, healer.player)
    with (
        patch("combat_turn_start.dice_roll", return_value=SimpleNamespace(total=damage)) as field,
        patch("check_resolution.dice_roll", return_value=_d20(3)) as save,
    ):
        call = game_tools(healer.sd, resolve_phase)
        result = await call("resolve_phase")
        if hp == 10:
            assert result["fate_offer"]["roller_id"] == ally
            assert (await healer.read(ally))["hp"]["current"] == 6
            assert not effects(result["packets"])
            healer.sd.combat_state = await healer.checkpoint()
            healer.sd.fate_offer = None
            result = await call("resolve_phase")
        assert field.call_count == 1
        assert save.call_count == (1 if hp == 10 else 0)
    tick = next(p for p in result["packets"] if p.get("automatic"))
    assert tick["source_id"] == mawling.id and tick["target_id"] == ally and tick["damage"] == damage
    assert [e["healed"] for e in effects([tick])] == ([1] if expected else [])
    saved = (await healer.checkpoint()).get_participant(ally)
    assert saved.is_fallen == saved.is_dead == (expected == 0)
    assert (await healer.read(ally))["hp"]["current"] == saved.hp_current == expected
