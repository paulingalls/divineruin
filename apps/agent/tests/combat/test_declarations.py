"""Tests for the typed declaration model (story-002): DeclarationType + resolve_declaration.

resolve_declaration is a PURE classify+validate function: it turns a raw declaration dict
(emitted by the DM into declare_phase) into a typed Declaration, or raises ValueError. The
six categories mirror gm_combat §Action Economy (L99-106); explicit ``type`` is required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _make_combat_state
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

from combat_turn import _declare_phase_impl
from declarations import DEFEND_AC_BONUS, Declaration, DeclarationType, ManeuverIntent, resolve_declaration


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
        assert d.maneuver_intent is None

    def test_maneuver_escape_intent_round_trips_as_enum(self):
        d = resolve_declaration({"type": "maneuver", "target_id": "goblin_1", "maneuver_intent": "escape"})
        assert d.maneuver_intent is ManeuverIntent.ESCAPE

    def test_unknown_maneuver_intent_fails_loud(self):
        with pytest.raises(ValueError, match="not a valid ManeuverIntent"):
            resolve_declaration({"type": "maneuver", "target_id": "goblin_1", "maneuver_intent": "shove"})

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


class TestReactionIsNoLongerADeclaration:
    """story-017 / AC5. A reaction is an INTERRUPT against an open Beat-3 window, so it is not a
    declaration at all — the category is deleted, not deprecated.

    Keeping it would relocate note 0f3945fa(d) onto the player: declare_phase would still accept
    `kind: "reaction"`, but validate_reaction_activation no longer reads pending_declarations, so
    a pre-declared reaction becomes a packet that can never activate and still consumes the
    actor's whole phase action.
    """

    def test_a_reaction_declaration_is_no_longer_a_declaration_type(self):
        with pytest.raises(ValueError, match="unknown declaration type"):
            resolve_declaration({"type": "reaction", "action": "warrior_brace_for_impact", "trigger": "on_hit"})

    def test_the_reaction_category_is_gone_from_the_vocabulary(self):
        assert "reaction" not in {t.value for t in DeclarationType}

    def test_a_declaration_carries_no_trigger_field(self):
        d = resolve_declaration({"type": "attack", "action": "Longsword", "target_id": "goblin_1"})
        assert not hasattr(d, "trigger")

    @pytest.mark.asyncio
    async def test_a_companion_reaction_declaration_burns_no_phase_action(self):
        """AC5's phase-action clause, on the actor the old design actually harmed.

        resolve_declaration never checked that the declaring actor could OWN the named reaction,
        so a companion's REACTION was accepted at Beat 1, was unactivatable (only players spend
        reactions), and cost the companion its entire round. advance_combat_phase validates every
        declaration BEFORE assigning any, so the whole payload is refused here and the beat stays
        open to re-declare — the companion loses nothing.
        """
        context = make_context()
        context.userdata.combat_state = _make_combat_state()
        mutations = MagicMock()
        mutations.save_combat_state = AsyncMock()

        with pytest.raises(ToolError, match="unknown declaration type"):
            await _declare_phase_impl(
                context,
                {
                    "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
                    "companion_kael": {
                        "type": "reaction",
                        "action": "warrior_brace_for_impact",
                        "trigger": "on_hit",
                    },
                },
                mutations=mutations,
            )

        state = context.userdata.combat_state
        assert state.beat == "declaration"
        assert state.pending_declarations == {}


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
