"""Tests for the enemy condition-infliction resolve path (M13 story-002).

Homes debt f9a5d1e88432: the temporary_hollowed charmed/frightened/poisoned immunity
gate in conditions.apply_condition had no live in-combat caller — this is the first one.
An enemy action_pool entry carrying {applies_condition, save, dc} routes through
_resolve_one_packet's ABILITY dispatch to _resolve_enemy_condition_packet, which rolls
the target's save and lands the condition via the immunity-gated apply_condition SSOT.
"""

from unittest.mock import MagicMock

from combat._helpers import _make_combat_state
from sample_fixtures import make_context

from combat_ability import _resolve_enemy_condition_packet
from combat_packet import _resolve_one_packet
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant, CombatState


def _enemy_action(cond_type="frightened", save="wisdom", dc=13):
    return {
        "name": "Unnerving Gaze",
        "applies_condition": cond_type,
        "save": save,
        "dc": dc,
        "properties": ["control"],
    }


def _get(state: CombatState, participant_id: str) -> CombatParticipant:
    """None-narrowing lookup for pyright (mirrors _player_conditions in
    test_combat_phase_conditions.py) — the fixture guarantees the id exists."""
    p = state.get_participant(participant_id)
    assert p is not None
    return p


def _state_with_enemy_action(action, *, player_conditions=None):
    state = _make_combat_state()
    _get(state, "goblin_scout_1").action_pool = [action]
    if player_conditions is not None:
        _get(state, "player_1").conditions = player_conditions
    return state


def _save_resolver(*, success: bool):
    result = MagicMock()
    result.success = success
    resolver = MagicMock()
    resolver.resolve_saving_throw = MagicMock(return_value=result)
    return resolver


class TestResolveEnemyConditionPacket:
    async def test_failed_save_lands_condition(self):
        state = _state_with_enemy_action(_enemy_action())
        attacker = _get(state, "goblin_scout_1")
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id="player_1")
        session = make_context().userdata

        summary = await _resolve_enemy_condition_packet(
            session,
            attacker,
            decl,
            _enemy_action(),
            state=state,
            conn=object(),
            save_resolver=_save_resolver(success=False),
        )

        assert summary["resolved"] is True
        assert summary["condition_applied"] == "frightened"
        assert "condition_resisted" not in summary
        assert any(c["type"] == "frightened" for c in _get(state, "player_1").conditions)

    async def test_successful_save_resists(self):
        state = _state_with_enemy_action(_enemy_action())
        attacker = _get(state, "goblin_scout_1")
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id="player_1")
        session = make_context().userdata

        summary = await _resolve_enemy_condition_packet(
            session,
            attacker,
            decl,
            _enemy_action(),
            state=state,
            conn=object(),
            save_resolver=_save_resolver(success=True),
        )

        assert summary["resolved"] is True
        assert summary["condition_resisted"] == "frightened"
        assert "condition_applied" not in summary
        assert not any(c["type"] == "frightened" for c in _get(state, "player_1").conditions)

    async def test_immune_target_no_ops_the_gate(self):
        """Debt f9a5d1e88432 regression guard: temporary_hollowed's charmed/frightened/poisoned
        immunity, exercised for the first time by a live in-combat caller."""
        state = _state_with_enemy_action(
            _enemy_action(cond_type="poisoned"),
            player_conditions=[{"type": "temporary_hollowed"}],
        )
        attacker = _get(state, "goblin_scout_1")
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id="player_1")
        session = make_context().userdata

        summary = await _resolve_enemy_condition_packet(
            session,
            attacker,
            decl,
            _enemy_action(cond_type="poisoned"),
            state=state,
            conn=object(),
            save_resolver=_save_resolver(success=False),
        )

        assert summary["resolved"] is True
        assert summary["condition_immune"] == "poisoned"
        assert "condition_applied" not in summary
        assert not any(c["type"] == "poisoned" for c in _get(state, "player_1").conditions)


class TestEnemyAbilityDispatch:
    async def test_enemy_condition_ability_routes_to_resolver_not_wasted(self):
        state = _state_with_enemy_action(_enemy_action())
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id="player_1")
        packet = MagicMock(actor_id="goblin_scout_1", declaration=decl)
        session = make_context().userdata
        mutations = MagicMock()
        queries = MagicMock()
        resolver = MagicMock()

        summary = await _resolve_one_packet(
            session,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=MagicMock(),
        )

        assert summary["resolved"] is True
        assert summary["declaration_type"] == str(DeclarationType.ABILITY)

    async def test_enemy_ability_without_applies_condition_still_wasted(self):
        state = _make_combat_state()
        _get(state, "goblin_scout_1").action_pool = [
            {"name": "Scimitar", "damage": "1d6", "damage_type": "slashing", "properties": []}
        ]
        decl = Declaration(type=DeclarationType.ABILITY, action="Scimitar", target_id="player_1")
        packet = MagicMock(actor_id="goblin_scout_1", declaration=decl)
        session = make_context().userdata
        mutations = MagicMock()
        queries = MagicMock()
        resolver = MagicMock()

        summary = await _resolve_one_packet(
            session,
            state,
            packet,
            mutations=mutations,
            queries=queries,
            resolver=resolver,
            concentration_break_mod=MagicMock(),
        )

        assert summary["resolved"] is False
