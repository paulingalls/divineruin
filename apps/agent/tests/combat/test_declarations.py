"""Tests for the typed declaration model (story-002): DeclarationType + resolve_declaration.

resolve_declaration is a PURE classify+validate function: it turns a raw declaration dict
(emitted by the DM into declare_phase) into a typed Declaration, or raises ValueError. The
six categories mirror gm_combat §Action Economy (L99-106); explicit ``type`` is required.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from archetype_abilities_config_fixture import load_fixture_config
from combat._helpers import _make_combat_state
from sample_fixtures import make_context

from combat_turn import _declare_phase_impl
from declarations import DEFEND_AC_BONUS, Declaration, DeclarationType, resolve_declaration
from query_tools import _query_abilities_impl


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

    def test_reaction_rejects_trigger_outside_the_window_vocabulary(self):
        # A prose trigger must fail HERE. Left unvalidated it can never match the ability's own
        # window at consumption (story-002), so the reaction would silently never fire.
        with pytest.raises(ValueError, match="trigger"):
            resolve_declaration({"type": "reaction", "action": "warrior_brace_for_impact", "trigger": "when hit"})

    @pytest.mark.parametrize("bad", [{"a": 1}, ["warrior_brace_for_impact"]])
    def test_reaction_rejects_non_string_action_as_value_error(self, bad):
        # Not merely "rejects": it must raise ValueError, the ONLY exception combat_turn
        # translates to ToolError. An unhashable action would otherwise TypeError out of the
        # ability lookup and crash the tool call instead of re-prompting the DM.
        with pytest.raises(ValueError, match="must be a string"):
            resolve_declaration({"type": "reaction", "action": bad, "trigger": "on_hit"})

    @pytest.mark.parametrize("bad", [{"a": 1}, ["on_hit"]])
    def test_reaction_rejects_non_string_trigger_as_value_error(self, bad):
        with pytest.raises(ValueError, match="trigger"):
            resolve_declaration({"type": "reaction", "action": "warrior_brace_for_impact", "trigger": bad})


@pytest.mark.asyncio
async def test_every_queried_reaction_window_is_accepted_by_declare_phase():
    """AC2, against the real catalog: EVERY reaction the payload can surface, for every class.

    One class's first reaction is not enough — a payload that emitted a constant "on_hit" would
    still be accepted for the reaction that happens to carry that window, so the pin has to walk
    the whole catalog for the payload and the gate to be unable to drift.
    """
    catalog = load_fixture_config().values()
    context = make_context()
    queries = MagicMock()
    persistence = MagicMock()
    persistence.get_character_abilities = AsyncMock(return_value=[])
    persistence.get_active_variant = AsyncMock(return_value=None)
    mutations = MagicMock()
    mutations.save_combat_state = AsyncMock()

    declared_ids = set()
    for player_class in sorted({ability.archetype_id for ability in catalog}):
        queries.get_player = AsyncMock(return_value={"class": player_class})
        payload = json.loads(await _query_abilities_impl(context, queries=queries, persistence=persistence))
        for reaction in [row for row in payload["abilities"] if row["ability_type"] == "reaction"]:
            context.userdata.combat_state = _make_combat_state()
            declarations = {
                "player_1": {"type": "reaction", "action": reaction["id"], "trigger": reaction["window"]},
                "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
            }

            result = json.loads(await _declare_phase_impl(context, declarations, mutations=mutations))

            assert result["beat"] == "resolution", reaction
            assert "player_1" in result["accepted_actors"], reaction
            declared_ids.add(reaction["id"])

    assert declared_ids == {ability.id for ability in catalog if ability.ability_type == "reaction"}


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
