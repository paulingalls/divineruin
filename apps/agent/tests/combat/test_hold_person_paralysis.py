"""Hold Person is a save-gated paralysis that ends on a Beat-4 WIS re-save.

Authored as a damage "0" attack, it crashed on a hit (bug 2a6d4b8a). It now rides the applies_condition
path Hollow Shriek already uses. paralyzed carries the tick_save its spell row describes ("re-saves each
turn"): a landed condition has no duration, so without the re-save the paralysis would never end.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

import check_resolution_attack
import concentration_break
from combat_packet import _resolve_one_packet, _resolve_tick_saves
from combat_phase import ResolutionPacket
from conditions import apply_condition, tick_conditions
from declarations import Declaration, DeclarationType

_CATALOG = json.loads((Path(__file__).resolve().parents[4] / "content" / "encounter_templates.json").read_text())


def _hold_person() -> dict:
    return next(
        dict(action)
        for encounter in _CATALOG
        for enemy in encounter["enemies"]
        for action in enemy["action_pool"]
        if action["name"] == "Hold Person"
    )


def test_hold_person_is_a_wisdom_save_against_paralysis():
    action = _hold_person()
    assert (action.get("applies_condition"), action.get("save"), action.get("dc")) == ("paralyzed", "wisdom", 12)


@pytest.mark.asyncio
@pytest.mark.parametrize(("save_face", "outcome"), [(1, "condition_inflicted"), (20, "condition_resisted")])
async def test_declared_hold_person_resolves_through_the_save_never_an_attack(save_face, outcome):
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    enemy.action_pool = [_hold_person()]
    hp_before = player.hp_current
    packet = ResolutionPacket(
        actor_id=enemy.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action="Hold Person", target_id=player.id),
        initiative=10,
    )

    with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=save_face)):
        summary = await _resolve_one_packet(
            make_context().userdata,
            state,
            packet,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            resolver=check_resolution_attack,
            concentration_break_mod=MagicMock(
                break_concentration_on_damage=AsyncMock(return_value=None),
                break_concentration_on_incapacitation=AsyncMock(return_value=None),
            ),
        )

    assert summary.get(outcome) == "paralyzed"
    assert "attacks" not in summary
    assert player.hp_current == hp_before


@pytest.mark.asyncio
async def test_hold_person_breaks_a_concentrating_players_spell():
    state = _make_combat_state()
    enemy = state.get_participant("goblin_scout_1")
    player = state.get_participant("player_1")
    assert enemy is not None and player is not None
    enemy.action_pool = [_hold_person()]
    session = make_context().userdata
    session.concentration.spell_id = "divine_bless"
    persist = AsyncMock()
    packet = ResolutionPacket(
        actor_id=enemy.id,
        declaration=Declaration(type=DeclarationType.ATTACK, action="Hold Person", target_id=player.id),
        initiative=10,
    )

    with (
        patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)),
        patch.object(concentration_break.db_mutations_concentration, "update_player_concentration", persist),
    ):
        summary = await _resolve_one_packet(
            session,
            state,
            packet,
            mutations=MagicMock(update_player_hp=AsyncMock()),
            queries=MagicMock(get_player_inventory=AsyncMock(return_value=[])),
            resolver=check_resolution_attack,
            concentration_break_mod=concentration_break,
            conn="phase-conn",
        )

    assert summary["condition_inflicted"] == "paralyzed"
    assert summary["concentration_broken"] == "divine_bless"
    assert session.concentration.spell_id is None
    persist.assert_awaited_once_with("player_1", None, conn="phase-conn")


def test_paralysis_surfaces_a_wisdom_re_save_at_each_wrap():
    _, events = tick_conditions(apply_condition([], "paralyzed", source="cult_leader"))
    assert events == [{"type": "paralyzed", "save": "wis", "source": "cult_leader"}]


@pytest.mark.parametrize(("success", "remaining"), [(True, []), (False, ["paralyzed"])])
def test_the_re_save_ends_paralysis_only_on_success(success, remaining):
    state = _make_combat_state()
    player = state.get_participant("player_1")
    assert player is not None
    player.conditions = apply_condition([], "paralyzed", source="cult_leader")
    _, events = tick_conditions(player.conditions)
    due = [{"actor_id": player.id, **event} for event in events]
    resolver = MagicMock()
    resolver.roll_participant_save = MagicMock(return_value=MagicMock(success=success))

    _resolve_tick_saves(state, due, resolver)

    assert [condition["type"] for condition in player.conditions] == remaining
