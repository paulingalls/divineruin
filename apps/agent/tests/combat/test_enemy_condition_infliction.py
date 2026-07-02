"""Tests for the enemy condition-infliction resolve path (M13 story-002).

Homes debt f9a5d1e88432: the temporary_hollowed charmed/frightened/poisoned immunity
gate in conditions.apply_condition had no live in-combat caller — this is the first one.
An enemy action_pool entry carrying {applies_condition, save, dc} routes through
_resolve_one_packet's dispatch to _resolve_enemy_condition_packet — for ATTACK *or* ABILITY
declarations (the DM declares enemy pool actions as ATTACK, system_prompts.py:235) — which rolls
the target's save and lands the condition via the immunity-gated apply_condition SSOT.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    # The resolver rolls the target's save via the shared roll_participant_save SSOT.
    result = MagicMock()
    result.success = success
    resolver = MagicMock()
    resolver.roll_participant_save = MagicMock(return_value=result)
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

    async def test_enemy_condition_action_routes_on_attack_declaration(self):
        # The DM declares enemy pool actions as ATTACK (system_prompts.py:235), not ABILITY —
        # the condition MUST inflict on the ATTACK path too, or the feature is a no-op in real
        # play (the ATTACK path would otherwise resolve a 0-damage swing and drop the condition).
        state = _state_with_enemy_action(_enemy_action())
        decl = Declaration(type=DeclarationType.ATTACK, action="Unnerving Gaze", target_id="player_1")
        packet = MagicMock(actor_id="goblin_scout_1", declaration=decl)
        session = make_context().userdata

        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):  # nat-1 -> save fails
            summary = await _resolve_one_packet(
                session,
                state,
                packet,
                mutations=MagicMock(),
                queries=MagicMock(),
                resolver=MagicMock(),
                concentration_break_mod=MagicMock(),
            )

        assert summary["resolved"] is True
        assert summary["condition_applied"] == "frightened"
        assert any(c["type"] == "frightened" for c in _get(state, "player_1").conditions)

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


class TestSaveThreading:
    async def test_resolver_forwards_role_dc_mod_and_passes_target_participant(self):
        # #3: the attacker's role dc_mod (Boss +2 / Elite +1) must reach the save DC; #4: the
        # TARGET participant (which carries saving_throw_proficiencies) is what's rolled, so a
        # proficient target gets its bonus. Both are threaded through roll_participant_save.
        state = _state_with_enemy_action(_enemy_action())
        attacker = _get(state, "goblin_scout_1")
        attacker.dc_mod = 2
        _get(state, "player_1").saving_throw_proficiencies = ["wisdom"]
        decl = Declaration(type=DeclarationType.ATTACK, action="Unnerving Gaze", target_id="player_1")
        session = make_context().userdata
        resolver = _save_resolver(success=True)

        await _resolve_enemy_condition_packet(
            session, attacker, decl, _enemy_action(), state=state, conn=object(), save_resolver=resolver
        )

        call = resolver.roll_participant_save.call_args
        assert call.kwargs["dc_mod"] == 2
        assert call.args[0] is _get(state, "player_1")  # target participant carries the proficiencies

    def test_roll_participant_save_honors_dc_mod_and_proficiency(self):
        # Real save math (no mock): dc_mod raises the effective DC; a proficient target gains the
        # proficiency bonus. Also exercises the "wis" -> "wisdom" abbreviation expansion.
        import check_resolution_save

        prof = CombatParticipant(
            id="prof",
            name="Prof",
            type="player",
            initiative=10,
            hp_current=10,
            hp_max=10,
            ac=12,
            attributes={"wisdom": 10},
            level=5,
            saving_throw_proficiencies=["wisdom"],
        )
        plain = CombatParticipant(
            id="plain",
            name="Plain",
            type="player",
            initiative=10,
            hp_current=10,
            hp_max=10,
            ac=12,
            attributes={"wisdom": 10},
            level=5,
        )
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)):
            r_prof = check_resolution_save.roll_participant_save(prof, "wis", 10, "frightened", dc_mod=3)
            r_plain = check_resolution_save.roll_participant_save(plain, "wis", 10, "frightened", dc_mod=3)

        assert r_prof.dc == 13 and r_plain.dc == 13  # dc + dc_mod
        assert r_prof.modifier > r_plain.modifier  # proficiency bonus folded in for the proficient target
