import copy
import json
from pathlib import Path

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import _activate, _ctx_at_resolution, _resolve_deps
from combat._reaction_helpers import _drain, _pause_at, _reaction_packet

import combat_reaction_effect
import conditions
import reaction_spend
import reaction_windows
from session_data import CombatParticipant

_CATALOG = json.loads((Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json").read_text())


def _grab() -> dict:
    return next(
        copy.deepcopy(action)
        for encounter in _CATALOG
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if enemy["id"] == "mawling_1" and action["name"] == "Seizing Grab"
    )


def _state():
    state = _ctx_at_resolution(player_hp=25, enemy_hp=18).userdata.combat_state
    enemy = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    enemy.id = "mawling_1"
    enemy.name = "Mawling"
    enemy.action_pool = [_grab()]
    state.initiative_order = ["player_1", enemy.id]
    state.pending_declarations = {
        player.id: {"type": "defend"},
        enemy.id: {"type": "attack", "action": "Seizing Grab", "target_id": player.id},
    }
    player.reaction_ids = ["rogue_slippery"]
    return state


@pytest.mark.asyncio
async def test_slippery_prevents_the_grapple_but_not_its_damage():
    ctx = _ctx_at_resolution(state=_state())
    deps = _resolve_deps(damage=2)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="mawling_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, "rogue_slippery", player_class="rogue")
    await _drain(ctx, deps, packets)

    player = ctx.userdata.combat_state.get_participant("player_1")
    assert player is not None
    assert player.hp_current == 23
    assert not conditions.has_condition(player.conditions, "grappled")
    assert _reaction_packet(packets)["mechanical_effect"] == "grapple_escaped"


@pytest.mark.asyncio
async def test_the_same_grab_unanswered_deals_damage_and_grapples():
    ctx = _ctx_at_resolution(state=_state())
    deps = _resolve_deps(damage=2)
    packets: list[dict] = []

    await _drain(ctx, deps, packets)

    player = ctx.userdata.combat_state.get_participant("player_1")
    assert player is not None
    assert player.hp_current == 23
    assert conditions.has_condition(player.conditions, "grappled")


@pytest.mark.asyncio
async def test_slippery_blocks_a_second_grab_without_removing_the_existing_one():
    state = _state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = conditions.apply_condition([], "grappled", source="mawling_0")
    ctx = _ctx_at_resolution(state=state)
    deps = _resolve_deps(damage=2)
    packets: list[dict] = []

    await _pause_at(ctx, deps, actor_id="mawling_1", stage=reaction_windows.POST_ROLL, packets=packets)
    await _activate(ctx, "rogue_slippery", player_class="rogue")
    await _drain(ctx, deps, packets)

    player = ctx.userdata.combat_state.get_participant("player_1")
    assert (
        next(condition for condition in player.conditions if condition["type"] == "grappled")["source"] == "mawling_0"
    )


def test_a_bystanders_malformed_spend_does_not_block_the_targets_grapple():
    state = _state()
    state.participants.append(
        CombatParticipant(id="player_2", name="Bram", type="player", initiative=10, hp_current=20, hp_max=20, ac=14)
    )
    head = {
        "seq": 4,
        "actor_id": "mawling_1",
        "declaration": {"type": "attack", "action": "Seizing Grab", "target_id": "player_1"},
    }
    window = reaction_windows.open_window_for(
        round_number=1,
        seq=4,
        stage=reaction_windows.POST_ROLL,
        actor_id="mawling_1",
        target_id="player_1",
        action_kind="attack",
        triggers=("on_condition_imposed",),
    )
    state.reactions_available["player_2"] = reaction_spend.spend("rogue_slippery", window, held_seq=4)

    spend = {"actor_id": "player_2", **state.reactions_available["player_2"]}
    assert combat_reaction_effect.grapple_blocked(state, head) is False
    assert combat_reaction_effect._apply(state, head, window, spend, _grab(), None) is None


def test_slippery_set_names_both_real_condition_imposed_reactions():
    catalog = load_fixture_config()
    assert frozenset({"rogue_slippery", "spy_slippery"}) == combat_reaction_effect.ESCAPES_GRAPPLE
    assert {catalog[ability_id].window for ability_id in combat_reaction_effect.ESCAPES_GRAPPLE} == {
        "on_condition_imposed"
    }
