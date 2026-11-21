"""Wall lines through the persisted declare, resolve and query tools."""

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from acceptance._capstone_helpers import _d20, _damage_die, _resolve_round
from acceptance._spatial_helpers import pos
from acceptance._spatial_helpers import spatial_entry as spatial_entry
from acceptance._structure_helpers import _move, _refuses, _reload, _save_and_reload, _strike
from acceptance.test_choir_encounter import search
from combat.test_spell_damage_lands import prepare_spell, saved_player
from voice_condition_fixtures import participant

import character_spells
import combat_hold
import combat_spatial
from combat_structures import add_wall
from combat_turn import declare_phase, resolve_phase
from creation_rules import build_character_data
from declaration_payloads import AbilityDecl, DefendDecl, ManeuverDecl, MultiattackDecl, StrikeSelection


@pytest.fixture
def mock_combat_agent_factory() -> None:
    return None


def caster_data(cls="mage"):
    return build_character_data("Caster", "human", cls, None, "", created_at=datetime(2026, 10, 1, tzinfo=UTC))


def ability(actor, action, *targets):
    return AbilityDecl(kind="ability", actor_id=actor, action=action, targets=list(targets), argument_type="")


def wall(state, x=10):
    return add_wall(state, "wall", "Slate Wall", pos(x, -5), pos(x, 5))


@pytest.mark.parametrize("x", [1, 10, 19])
async def test_melee_refuses_the_whole_line_and_lands_with_a_clear_line(spatial_entry, x) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    player, target = ctx.userdata.player_id, "mawling_1"
    combat_spatial.place(state, player, pos())
    combat_spatial.place(state, target, pos(x + 1))
    wall(state, x)
    state = await _save_and_reload(ctx)
    strike = _strike(player, target)
    await _refuses(ctx, strike, r"Slate Wall \(wall\)")
    combat_spatial.place(state, target, pos(0, 10))
    state = await _save_and_reload(ctx)
    hp = participant(state, target).hp_current
    await declare_phase(ctx, [strike, DefendDecl(reshape=[], kind="defend", actor_id=target)])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await _resolve_round(ctx)
    assert participant(await _reload(ctx), target).hp_current < hp


@pytest.mark.parametrize("spell", ["arcane_bolt", "divine_sacred_flame", "divine_heal_wounds"])
async def test_single_spell_refuses_before_spending(spatial_entry, spell) -> None:
    ctx, _ = await spatial_entry(caster_data("mage" if spell.startswith("arcane") else "cleric"), members=2)
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    target = next(p.id for p in state.participants if p.is_ally and p.id != player) if "heal" in spell else "mawling_1"
    await prepare_spell(ctx, spell)
    await character_spells.record_learned(player, spell, "discovery")
    combat_spatial.place(state, player, pos())
    combat_spatial.place(state, target, pos(15))
    wall(state)
    await _save_and_reload(ctx)
    declaration = ability(player, spell, target)
    before = await saved_player(player)
    await _refuses(ctx, declaration, r"Slate Wall \(wall\)")
    assert await saved_player(player) == before
    state = ctx.userdata.combat_state
    recipient = participant(state, target)
    if "heal" in spell:
        recipient.hp_current = 3
    hp = recipient.hp_current
    combat_spatial.place(state, target, pos(3))
    await _save_and_reload(ctx)
    await declare_phase(ctx, [declaration])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20 if spell == "arcane_bolt" else 1)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
        patch("dice.roll", return_value=_damage_die(4)),
    ):
        await _resolve_round(ctx)
    landed = participant(await _reload(ctx), target).hp_current
    assert landed > hp if "heal" in spell else landed < hp


@pytest.mark.parametrize("crossing_anchor", [False, True])
async def test_fireball_uses_the_anchor_line_and_can_damage_a_wall(spatial_entry, crossing_anchor) -> None:
    ctx, _ = await spatial_entry(caster_data())
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    anchor, blocked = "mawling_1", "mawling_2"
    spell = "arcane_fireball"
    await prepare_spell(ctx, spell)
    await character_spells.record_learned(player, spell, "discovery")
    for actor_id, point in [(player, pos(-20)), (anchor, pos(14)), (blocked, pos(6))]:
        combat_spatial.place(state, actor_id, point)
    for target_id in (anchor, blocked):
        # Survive a failed DEX save, so the fight continues and the packet shape is fixed.
        participant(state, target_id).hp_current = participant(state, target_id).hp_max = 200
    wall(state)
    if crossing_anchor:
        add_wall(state, "hidden_wall", "Hidden Wall", pos(5), pos(15))
        anchor = "wall"
    else:
        add_wall(state, "hidden_wall", "Hidden Wall", pos(4, -5), pos(4, 5))
    state = await _save_and_reload(ctx)
    before = {p.id: p.hp_current for p in state.participants}
    await declare_phase(
        ctx, [AbilityDecl(kind="ability", actor_id=player, action=spell, targets=[anchor], argument_type="")]
    )
    with patch("dice.roll", return_value=_damage_die(4)):
        result = await _resolve_round(ctx)
    cast = next(p["cast"] for p in result["packets"] if p["actor_id"] == player)
    # Centred on walls that meet at the anchor, the blast runs along both of them.
    reached = {"wall", "hidden_wall", "mawling_1", blocked} if crossing_anchor else {anchor, "wall"}
    assert {p["target_id"] for p in cast["damage_results"]} == reached
    saved = await _reload(ctx)
    for target_id in (blocked, "hidden_wall"):
        assert (participant(saved, target_id).hp_current < before[target_id]) == crossing_anchor
    assert participant(saved, "wall").hp_current < before["wall"]


async def test_melee_reaches_the_nearest_end_of_a_wall(spatial_entry) -> None:
    ctx, _ = await spatial_entry()
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    combat_spatial.place(state, player, pos(10, -20))
    wall(state)
    add_wall(state, "crosspiece", "Crosspiece", pos(8, -2), pos(12, -2))
    await _save_and_reload(ctx)
    await declare_phase(ctx, [_strike(player, "wall")])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        result = await _resolve_round(ctx)
    strike = next(p for p in result["packets"] if p["actor_id"] == player)
    assert strike["destination"] == pos(10, -10)
    assert participant(await _reload(ctx), "wall").hp_current < 30


@pytest.mark.parametrize(
    ("encounter", "enemy", "action"),
    [
        ("bandit_ambush", "bandit_1", "Short Sword"),
        ("bandit_ambush", "bandit_1", "Light Crossbow"),
        ("cult_cell", "cult_fanatic_1", "Inflict Wounds"),
        ("hollow_choir", "choir_zone", "Dissonant Chord"),
        ("hollow_choir", "choir_zone", "Stolen Melody"),
    ],
)
async def test_enemy_direct_attack_or_condition_uses_the_same_line(spatial_entry, encounter, enemy, action) -> None:
    ctx, _ = await spatial_entry(encounter=encounter)
    if enemy == "choir_zone":
        await search(ctx)
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    combat_spatial.place(state, enemy, pos())
    combat_spatial.place(state, player, pos(12))
    wall(state)
    state = await _save_and_reload(ctx)
    charm = action == "Stolen Melody"
    declaration = ability(enemy, action, player) if charm else _strike(enemy, player, action)
    await _refuses(ctx, declaration, r"Slate Wall \(wall\)")
    combat_spatial.place(state, player, pos(2))
    hp = participant(state, player).hp_current
    await _save_and_reload(ctx)
    await declare_phase(ctx, [declaration])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(1 if charm else 20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
        patch("dice.roll", return_value=_damage_die(3)),
    ):
        result = await _resolve_round(ctx)
    assert any(p["actor_id"] == enemy and p["resolved"] for p in result["packets"])
    recipient = participant(await _reload(ctx), player)
    if charm:
        assert any(p.get("condition_inflicted") == "charmed" for p in result["packets"])
        assert any(c["type"] == "charmed" for c in recipient.conditions)
    else:
        assert recipient.hp_current < hp


async def test_ranged_target_wall_is_exempt_only_from_its_own_segment(spatial_entry) -> None:
    ctx, _ = await spatial_entry(caster_data("beastcaller"))
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    combat_spatial.place(state, player, pos())
    wall(state)
    add_wall(state, "target_wall", "Target Wall", pos(20, -5), pos(20, 5))
    state = await _save_and_reload(ctx)
    await _refuses(ctx, _strike(player, "target_wall", "Shortbow"), r"Slate Wall \(wall\)")
    await declare_phase(ctx, [_strike(player, "wall", "Shortbow")])
    with (
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(4)),
    ):
        await _resolve_round(ctx)
    assert participant(await _reload(ctx), "wall").hp_current < 30


@pytest.mark.parametrize("action", ["Greataxe", "Shortbow", "arcane_bolt", "shove"])
async def test_added_wall_wastes_a_ready_allied_delivery(spatial_entry, action) -> None:
    ctx, _ = await spatial_entry(caster_data({"Shortbow": "beastcaller", "arcane_bolt": "mage"}.get(action, "warrior")))
    state = ctx.userdata.combat_state
    player, target = ctx.userdata.player_id, "mawling_1"
    combat_spatial.place(state, player, pos())
    combat_spatial.place(state, target, pos(15))
    if action == "arcane_bolt":
        await character_spells.record_learned(player, action, "discovery")
    await _save_and_reload(ctx)
    before = await saved_player(player)
    if action == "shove":
        declaration = ManeuverDecl(kind="maneuver", actor_id=player, target_id=target)
    elif action == "arcane_bolt":
        declaration = ability(player, action, target)
    else:
        declaration = _strike(player, target, action)
    await declare_phase(ctx, [declaration])
    wall(ctx.userdata.combat_state, x=12)
    state = await _save_and_reload(ctx)
    hp = participant(state, target).hp_current
    with patch("check_resolution.dice_roll", return_value=_d20(20)) as dice:
        result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == player)
    assert not packet["resolved"] and "Slate Wall (wall)" in packet["reason"]
    dice.assert_not_called()
    saved = await _reload(ctx)
    assert participant(saved, target).hp_current == hp
    assert combat_spatial.require_spatial(saved)["positions"][player] == pos()
    assert (await saved_player(player)).get("focus") == before.get("focus")


@pytest.mark.parametrize("blocked", [True, False])
async def test_held_shot_checks_line_before_reaction_or_roll(spatial_entry, blocked) -> None:
    ctx, _ = await spatial_entry(caster_data("skirmisher"), encounter="bandit_ambush")
    state = ctx.userdata.combat_state
    player, enemy = ctx.userdata.player_id, "bandit_1"
    combat_spatial.place(state, enemy, pos())
    combat_spatial.place(state, player, pos(15, 10))
    wall(state)
    state = await _save_and_reload(ctx)
    hp = participant(state, player).hp_current
    await declare_phase(
        ctx, [_move(player, pos(15) if blocked else pos(15, 12)), _strike(enemy, player, "Light Crossbow")]
    )
    with (
        patch("combat_hold.roll_hostile", wraps=combat_hold.roll_hostile) as roll,
        patch("check_resolution.dice_roll", return_value=_d20(20)),
        patch("check_resolution_attack.dice_roll", return_value=_damage_die(3)),
    ):
        await resolve_phase(ctx)
        after_allies = json.loads(await resolve_phase(ctx))
        await _reload(ctx)
        if blocked:
            assert after_allies["next"]["waiting_on"] is None
            assert not ctx.userdata.combat_state.held_actions
            packet = next(p for p in after_allies["packets"] if p["actor_id"] == enemy)
            assert not packet["resolved"] and "Slate Wall (wall)" in packet["reason"]
            roll.assert_not_called()
        else:
            assert after_allies["next"]["waiting_on"] is not None
            await _resolve_round(ctx)
            roll.assert_awaited_once()
    saved = await _reload(ctx)
    assert (participant(saved, player).hp_current == hp) == blocked
    assert (participant(saved, enemy).last_action_execution is None) == blocked
    assert not saved.held_actions


async def test_multiattack_refuses_the_blocked_child_without_saving_the_clear_one(spatial_entry) -> None:
    ctx, _ = await spatial_entry(members=2, encounter="hollow_mawling_pack")
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    ally = next(p.id for p in state.participants if p.is_ally and p.id != player)
    enemy = next(p for p in state.participants if not p.is_ally)
    for pid, point in [(enemy.id, pos()), (player, pos(2)), (ally, pos(12))]:
        combat_spatial.place(state, pid, point)
    wall(state)
    await _save_and_reload(ctx)
    declaration = MultiattackDecl(
        kind="multiattack",
        actor_id=enemy.id,
        action="Multiattack",
        strikes=[
            StrikeSelection(action="Claw", target_id=player, held_item_id=""),
            StrikeSelection(action="Dissolution Maw", target_id=ally, held_item_id=""),
        ],
    )
    await _refuses(ctx, declaration, r"Slate Wall \(wall\)")


async def test_inspire_rechecks_an_explicit_ally_and_keeps_its_focus(spatial_entry) -> None:
    ctx, _ = await spatial_entry(caster_data("bard"), members=2)
    state = ctx.userdata.combat_state
    player = ctx.userdata.player_id
    ally = next(p.id for p in state.participants if p.is_ally and p.id != player)
    combat_spatial.place(state, player, pos())
    combat_spatial.place(state, ally, pos(12))
    await _save_and_reload(ctx)
    focus = (await saved_player(player))["focus"]
    inspire = ability(player, "bard_inspire", ally)
    await declare_phase(ctx, [inspire])
    wall(ctx.userdata.combat_state)
    await _save_and_reload(ctx)
    result = await _resolve_round(ctx)
    packet = next(p for p in result["packets"] if p["actor_id"] == player)
    assert not packet["resolved"] and "Slate Wall (wall)" in packet["reason"]
    assert (await saved_player(player))["focus"] == focus
    await _refuses(ctx, inspire, r"Slate Wall \(wall\)")
    combat_spatial.place(ctx.userdata.combat_state, ally, pos(4))
    await _save_and_reload(ctx)
    await declare_phase(ctx, [inspire])
    result = await _resolve_round(ctx)
    assert any(p.get("condition_applied") == "inspired" for p in result["packets"])
    assert any(c["type"] == "inspired" for c in participant(await _reload(ctx), ally).conditions)
