"""Tests for the typed declaration model (story-002): DeclarationType + resolve_declaration.

resolve_declaration is a PURE classify+validate function: it turns a raw declaration dict
(emitted by the DM into declare_phase) into a typed Declaration, or raises ValueError. The
six categories mirror gm_combat §Action Economy (L99-106); explicit ``type`` is required.
"""

import pytest

from declarations import DEFEND_AC_BONUS, Declaration, DeclarationType, resolve_declaration


class TestResolveDeclarationValid:
    def test_attack_requires_action_and_target(self):
        d = resolve_declaration({"type": "attack", "action": "Longsword", "target_id": "goblin_1"})
        assert d == Declaration(type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_1")

    def test_ability_requires_action_target_optional(self):
        d = resolve_declaration({"type": "ability", "action": "Fireball"})
        assert d.type is DeclarationType.ABILITY
        assert d.action == "Fireball"
        assert d.target_id is None

    def test_ability_keeps_target_when_present(self):
        d = resolve_declaration({"type": "ability", "action": "Smite", "target_id": "goblin_1"})
        assert d.target_id == "goblin_1"

    def test_interact_requires_action(self):
        d = resolve_declaration({"type": "interact", "action": "healing potion"})
        assert d.type is DeclarationType.INTERACT
        assert d.action == "healing potion"

    def test_maneuver_requires_target(self):
        d = resolve_declaration({"type": "maneuver", "target_id": "goblin_1"})
        assert d.type is DeclarationType.MANEUVER
        assert d.target_id == "goblin_1"

    def test_defend_yields_ac_bonus_and_no_attack(self):
        d = resolve_declaration({"type": "defend"})
        assert d.type is DeclarationType.DEFEND
        assert d.ac_bonus == DEFEND_AC_BONUS == 2
        assert d.action is None
        assert d.target_id is None

    def test_retreat_needs_no_fields(self):
        d = resolve_declaration({"type": "retreat"})
        assert d.type is DeclarationType.RETREAT
        assert d.ac_bonus == 0

    def test_type_is_case_insensitive(self):
        d = resolve_declaration({"type": "ATTACK", "action": "Longsword", "target_id": "goblin_1"})
        assert d.type is DeclarationType.ATTACK

    def test_rider_passes_through_when_present(self):
        # The chosen enhancer rider (e.g. Cunning Action's dash/disengage/hide) is carried
        # verbatim into the typed Declaration for downstream resolution (story-004).
        d = resolve_declaration({"type": "attack", "action": "Dagger", "target_id": "goblin_1", "rider": "hide"})
        assert d.rider == "hide"

    def test_rider_defaults_none(self):
        d = resolve_declaration({"type": "attack", "action": "Longsword", "target_id": "goblin_1"})
        assert d.rider is None

    def test_argument_type_passes_through_for_de_escalate(self):
        # M15 story-002: a de_escalate ABILITY carries the argument category the Diplomat makes.
        # resolve_declaration is shape-only — it threads argument_type verbatim; the value is
        # validated against social_resolution.ARGUMENT_TYPES at the packet boundary, not here.
        d = resolve_declaration({"type": "ability", "action": "de_escalate", "argument_type": "reason"})
        assert d.argument_type == "reason"

    def test_argument_type_defaults_none(self):
        d = resolve_declaration({"type": "ability", "action": "Fireball"})
        assert d.argument_type is None

    def test_argument_type_not_validated_at_shape_boundary(self):
        # Shape-only: an unknown category is NOT rejected here (the packet boundary owns that).
        d = resolve_declaration({"type": "ability", "action": "de_escalate", "argument_type": "nonsense"})
        assert d.argument_type == "nonsense"

    def test_reaction_requires_action_and_trigger(self):
        # story-001: a REACTION declaration names a reaction ability plus the trigger window
        # it's firing against. Relies on the autouse seed_abilities fixture (real content).
        d = resolve_declaration({"type": "reaction", "action": "warrior_brace_for_impact", "trigger": "on_hit"})
        assert d == Declaration(type=DeclarationType.REACTION, action="warrior_brace_for_impact", trigger="on_hit")

    def test_trigger_defaults_none_for_non_reaction_types(self):
        d = resolve_declaration({"type": "attack", "action": "Longsword", "target_id": "goblin_1"})
        assert d.trigger is None


class TestReactionDeclarationInvalid:
    def test_reaction_without_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            resolve_declaration({"type": "reaction", "trigger": "on_hit"})

    def test_reaction_without_trigger_raises(self):
        with pytest.raises(ValueError, match="trigger"):
            resolve_declaration({"type": "reaction", "action": "warrior_brace_for_impact"})

    def test_reaction_rejects_non_reaction_ability(self):
        with pytest.raises(ValueError, match="not a reaction ability"):
            resolve_declaration({"type": "reaction", "action": "warrior_devastating_strike", "trigger": "on_hit"})

    def test_reaction_rejects_unknown_ability(self):
        with pytest.raises(ValueError, match="Unknown ability"):
            resolve_declaration({"type": "reaction", "action": "no_such_ability", "trigger": "on_hit"})


class TestResolveDeclarationInvalid:
    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="type"):
            resolve_declaration({"action": "Longsword", "target_id": "goblin_1"})

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="unknown declaration type"):
            resolve_declaration({"type": "teleport"})

    def test_attack_without_target_raises(self):
        with pytest.raises(ValueError, match="target_id"):
            resolve_declaration({"type": "attack", "action": "Longsword"})

    def test_attack_without_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            resolve_declaration({"type": "attack", "target_id": "goblin_1"})

    def test_ability_without_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            resolve_declaration({"type": "ability", "target_id": "goblin_1"})

    def test_interact_without_action_raises(self):
        with pytest.raises(ValueError, match="action"):
            resolve_declaration({"type": "interact"})

    def test_maneuver_without_target_raises(self):
        with pytest.raises(ValueError, match="target_id"):
            resolve_declaration({"type": "maneuver"})

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError, match="type"):
            resolve_declaration({})


class TestDeclarationIsImmutable:
    def test_frozen(self):
        d = resolve_declaration({"type": "defend"})
        with pytest.raises((AttributeError, TypeError)):
            d.ac_bonus = 99  # type: ignore[misc]
