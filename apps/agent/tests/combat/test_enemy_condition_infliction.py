"""Enemy pool actions can be declared as ATTACK or ABILITY; both must reach immunity-gated condition application."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from combat._helpers import _make_combat_state
from sample_fixtures import make_context

from check_resolution_save import SavingThrowResult
from combat_enemy_action import _resolve_enemy_condition_packet
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
    # The resolver rolls the target's save via the shared roll_participant_save SSOT. The result
    # is the real type: a MagicMock answers any field the production code reads with a truthy mock.
    result = SavingThrowResult(
        save_type="wisdom",
        roll=12 if success else 10,
        modifier=0,
        total=12 if success else 10,
        dc=12,
        success=success,
        margin=0 if success else -2,
        effect_applied=None,
        narrative_hint="",
    )
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
        assert summary["condition_inflicted"] == "frightened"
        assert "condition_resisted" not in summary
        assert "save_advantage" not in summary
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
        assert "condition_inflicted" not in summary
        assert not any(c["type"] == "frightened" for c in _get(state, "player_1").conditions)

    async def test_immune_target_no_ops_the_gate(self):
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
        assert "condition_inflicted" not in summary
        assert not any(c["type"] == "poisoned" for c in _get(state, "player_1").conditions)

    async def test_missing_target_id_wastes_and_does_not_self_inflict(self):
        state = _state_with_enemy_action(_enemy_action())
        attacker = _get(state, "goblin_scout_1")
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id=None)
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

        assert summary["resolved"] is False
        assert "condition_inflicted" not in summary
        assert not any(c["type"] == "frightened" for c in attacker.conditions)  # enemy not self-inflicted

    async def test_explicit_self_target_id_wastes(self):
        state = _state_with_enemy_action(_enemy_action())
        attacker = _get(state, "goblin_scout_1")
        decl = Declaration(type=DeclarationType.ABILITY, action="Unnerving Gaze", target_id="goblin_scout_1")
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

        assert summary["resolved"] is False
        assert "condition_inflicted" not in summary
        assert not any(c["type"] == "frightened" for c in attacker.conditions)


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
        assert summary["condition_inflicted"] == "frightened"
        assert any(c["type"] == "frightened" for c in _get(state, "player_1").conditions)

    async def test_condition_action_does_not_consume_opening_strike_beat(self):
        # A save-based condition action is not an attack roll — it must NOT consume the opening-strike
        # dramatic beat (first_attack_resolved), so the combat's first real ATTACK still earns the
        # dramatic opener. (Regression: an earlier fix set the flag in dispatch, even for a wasted action.)
        state = _state_with_enemy_action(_enemy_action())
        assert state.first_attack_resolved is False
        decl = Declaration(type=DeclarationType.ATTACK, action="Unnerving Gaze", target_id="player_1")
        packet = MagicMock(actor_id="goblin_scout_1", declaration=decl)
        session = make_context().userdata

        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=1)):
            await _resolve_one_packet(
                session,
                state,
                packet,
                mutations=MagicMock(),
                queries=MagicMock(),
                resolver=MagicMock(),
                concentration_break_mod=MagicMock(),
            )

        assert state.first_attack_resolved is False

    async def test_ally_condition_action_is_not_routed_to_hostile_resolver(self):
        # is_ally gate: a companion (ally) action carrying applies_condition must NOT route to the
        # hostile enemy-condition resolver (which rolls the target's save to RESIST — wrong for a
        # friendly effect). Latent today (no ally content has applies_condition); guards future content.
        state = _state_with_enemy_action(_enemy_action())
        _get(state, "goblin_scout_1").type = "companion"  # an ally (is_ally True)
        decl = Declaration(type=DeclarationType.ATTACK, action="Unnerving Gaze", target_id="player_1")
        packet = MagicMock(actor_id="goblin_scout_1", declaration=decl)
        session = make_context().userdata

        with patch("combat_enemy_action._resolve_enemy_condition_packet") as mock_enemy_cond:
            with patch(
                "combat_packet._resolve_attack_packet", return_value={"hit": False, "critical": False}
            ) as attack:
                await _resolve_one_packet(
                    session,
                    state,
                    packet,
                    mutations=MagicMock(),
                    queries=MagicMock(),
                    resolver=MagicMock(),
                    concentration_break_mod=MagicMock(),
                )

        mock_enemy_cond.assert_not_called()
        attack.assert_awaited_once()

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

    def test_include_proficiency_false_preserves_tick_clear_odds(self):
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
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)):
            r_incl = check_resolution_save.roll_participant_save(
                prof, "wis", 10, "frightened", include_proficiency=True
            )
            r_excl = check_resolution_save.roll_participant_save(
                prof, "wis", 10, "frightened", include_proficiency=False
            )

        assert r_incl.modifier > r_excl.modifier  # proficiency folded in only when include_proficiency=True

    def test_uppercase_save_abbrev_does_not_diverge_load_gate_vs_runtime(self):
        import check_resolution_save

        assert check_resolution_save.is_valid_save_key("WIS") is True
        p = CombatParticipant(
            id="p",
            name="P",
            type="player",
            initiative=10,
            hp_current=10,
            hp_max=10,
            ac=12,
            attributes={"wisdom": 10},
            level=3,
        )
        with patch("check_resolution.dice_roll", return_value=SimpleNamespace(total=10)):
            r = check_resolution_save.roll_participant_save(p, "WIS", 12, "frightened")  # must NOT raise
        assert r.save_type == "wisdom"
