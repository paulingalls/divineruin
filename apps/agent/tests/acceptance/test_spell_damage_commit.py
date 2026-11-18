"""Damage casts commit Hollow destruction and roll back HP with Focus atomically."""

import json
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _hollow_resonance_fixtures import hollow
from acceptance._capstone_helpers import _d20, _enemy, _resolve_round
from acceptance._catalog_cutover_helpers import started as started
from combat.test_spell_damage_lands import declare_spell, load_combat, prepare_spell, saved_player
from combat.test_spell_damage_lands import spell_fight as spell_fight
from voice_condition_fixtures import participant

import combat_hollow_death
import db
import db_mutations


@pytest.fixture
async def dev_db_pool(reset_db_pool):
    return await db.get_pool()


@pytest.mark.parametrize("spell_id", ["arcane_bolt", "arcane_magic_missile"])
async def test_spell_destroyed_hollow_receipt_and_resonance_persist_once(spell_fight, spell_id, monkeypatch):
    ctx = spell_fight
    await prepare_spell(ctx, spell_id)
    state = ctx.userdata.combat_state
    target = hollow("foe")
    target.hp_current = 1
    state.participants[1] = target
    survivor = _enemy("survivor", 100)
    state.participants.append(survivor)
    state.initiative_order.append(survivor.id)
    from voice_condition_fixtures import place_actors

    place_actors(state)
    death = AsyncMock(wraps=combat_hollow_death.accrue_death)
    monkeypatch.setattr(combat_hollow_death, "accrue_death", death)
    await declare_spell(ctx, spell_id)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    loaded = await load_combat(state.combat_id)
    victim = participant(loaded, "foe")
    assert victim.hp_current == 0 and victim.is_dead and victim.is_fallen and victim.hollow_death_resolved
    death.assert_awaited_once()
    assert target.hollow is not None
    total = cast["resonance_generated"] + target.hollow["resonance_on_death"] - 1
    player = await saved_player(ctx.userdata.player_id)
    assert player["resonance"]["current"] == ctx.userdata.resonance.current == max(0, total)
    ctx.userdata.combat_state = loaded
    import combat_turn
    from declaration_payloads import DefendDecl

    await combat_turn.declare_phase(ctx, [DefendDecl(kind="defend", actor_id=ctx.userdata.player_id)])
    await _resolve_round(ctx)
    death.assert_awaited_once()
    assert ctx.userdata.resonance.current == max(0, total - 1)


async def test_last_hollow_spell_kill_ends_normally(spell_fight):
    ctx = spell_fight
    state = ctx.userdata.combat_state
    target = hollow("foe")
    target.hp_current = 1
    state.participants[1] = target
    await declare_spell(ctx)
    with (
        patch("check_resolution.dice_roll", return_value=_d20(15)),
        patch("check_resolution_attack.dice_roll", return_value=SimpleNamespace(total=7)),
    ):
        result = await _resolve_round(ctx)
    assert json.loads(result[1])["outcome"] == "victory"
    assert ctx.userdata.combat_state is None
    assert await db_mutations.load_combat_state(state.combat_id) is None


async def test_paid_damage_rolls_back_hp_focus_and_events_then_retries_once(spell_fight, monkeypatch):
    ctx = spell_fight
    spell = await prepare_spell(ctx, "arcane_magic_missile")
    await declare_spell(ctx, spell.id)
    state = deepcopy(ctx.userdata.combat_state.to_dict())
    player = await saved_player(ctx.userdata.player_id)
    mirrors = asdict(ctx.userdata.party)
    ctx.userdata.room.local_participant.publish_data.reset_mock()
    original = db_mutations.save_combat_state
    observed = []

    async def fail_after_write(combat_id, data, *, conn=None):
        await original(combat_id, data, conn=conn)
        written = await load_combat(combat_id, conn=conn)
        changed = await saved_player(ctx.userdata.player_id, conn=conn)
        assert participant(written, "foe").hp_current < 100
        assert changed["focus"]["current"] == player["focus"]["current"] - spell.focus_cost
        observed.append(True)
        raise RuntimeError("injected after damage and Focus writes")

    with monkeypatch.context() as fault:
        fault.setattr(db_mutations, "save_combat_state", fail_after_write)
        with pytest.raises(RuntimeError, match="injected after damage"):
            await _resolve_round(ctx)
    assert observed == [True]
    assert (await load_combat(state["combat_id"])).to_dict() == state
    assert await saved_player(ctx.userdata.player_id) == player
    assert ctx.userdata.combat_state.to_dict() == state and asdict(ctx.userdata.party) == mirrors
    ctx.userdata.room.local_participant.publish_data.assert_not_called()
    result = await _resolve_round(ctx)
    damage = next(
        p["cast"]["damage_result"]["damage"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id
    )
    assert participant(ctx.userdata.combat_state, "foe").hp_current == 100 - damage
    assert (await saved_player(ctx.userdata.player_id))["focus"]["current"] == player["focus"][
        "current"
    ] - spell.focus_cost


@pytest.mark.parametrize(
    "spell_id,broken", [("arcane_bolt", "divine_bless"), ("primal_call_lightning", "primal_call_lightning")]
)
async def test_redirected_spell_damage_breaks_real_concentration(started, spell_id, broken):
    from acceptance.test_choir_encounter import search

    import combat_turn
    import db_mutations_concentration
    from declaration_payloads import AbilityDecl, DefendDecl

    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    pid = ctx.userdata.player_id
    if spell_id != "arcane_bolt":
        import character_spells

        await prepare_spell(ctx, spell_id)
        await character_spells.record_learned(pid, spell_id, "discovery")
    prior = "divine_bless" if spell_id == "arcane_bolt" else None
    ctx.userdata.concentration.spell_id = prior
    await db_mutations_concentration.update_player_concentration(pid, prior)
    participant(ctx.userdata.combat_state, pid).conditions = (
        [{"type": "blessed", "source": "divine_bless"}] if prior else []
    )
    await combat_turn.declare_phase(
        ctx,
        [
            AbilityDecl(kind="ability", actor_id=pid, action=spell_id, targets=["choir_zone"], argument_type=""),
            DefendDecl(kind="defend", actor_id="choir_zone"),
        ],
    )
    import random

    import check_resolution_attack
    import check_resolution_save

    attack = check_resolution_attack.resolve_attack
    save = check_resolution_save.resolve_saving_throw

    def fixed_attack(*args, **kwargs):
        return attack(*args, **{**kwargs, "rng": random.Random(0)})

    def fixed_save(*args, **kwargs):
        return save(*args, **{**kwargs, "rng": random.Random(5 if args[3] == "Aura of Lost Voices" else 31)})

    with (
        patch("check_resolution_attack.resolve_attack", side_effect=fixed_attack),
        patch("check_resolution_save.resolve_saving_throw", side_effect=fixed_save),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == pid)
    assert cast["damage_result"]["damage"] > 0
    assert cast["damage_result"]["target_id"] == pid
    assert cast["damage_result"]["concentration_broken"] == broken
    assert ctx.userdata.concentration.spell_id is None
    assert (await saved_player(pid))["concentration"]["spell_id"] is None
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert not participant(saved, pid).conditions


async def test_mixed_spell_filters_choir_components_before_one_hp_landing(started):
    import random

    from acceptance.test_choir_encounter import search

    import character_spells
    import check_resolution_save
    import combat_turn
    from declaration_payloads import AbilityDecl, DefendDecl

    ctx, _ = await started("hollow_choir", player_class="mage")
    await search(ctx)
    spell = await prepare_spell(ctx, "divine_flame_strike")
    await character_spells.record_learned(ctx.userdata.player_id, spell.id, "discovery")
    await combat_turn.declare_phase(
        ctx,
        [
            AbilityDecl(
                kind="ability",
                actor_id=ctx.userdata.player_id,
                action=spell.id,
                targets=["choir_zone"],
                argument_type="",
            ),
            DefendDecl(kind="defend", actor_id="choir_zone"),
        ],
    )
    save = check_resolution_save.resolve_saving_throw

    def fixed_save(*args, **kwargs):
        return save(*args, **{**kwargs, "rng": random.Random(31 if args[3] == spell.name else 5)})

    with (
        patch("check_resolution_save.resolve_saving_throw", side_effect=fixed_save),
        patch("dice.roll", return_value=SimpleNamespace(total=3)),
    ):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == ctx.userdata.player_id)
    damage = cast["damage_result"]
    assert damage["target_id"] == "choir_zone" and damage["damage"] == 6
    assert [(c["damage_type"], c["damage"]) for c in damage["damage_components"]] == [("fire", 0), ("radiant", 6)]
    saved = await load_combat(ctx.userdata.combat_state.combat_id)
    assert participant(saved, "choir_zone").hp_current == 194
