"""M4.4 story-005 — JSONB read-boundary validation for persistent conditions (AC2).

A corrupt stored condition dict (unknown type / non-int stacks) must fail loud at the read
boundary (read_player_conditions) rather than load green and crash a resolver later. The pure
validators live in conditions.py; the DB-level fail-loud is exercised against the dev DB.
"""

import json
from unittest.mock import AsyncMock

import pytest

import conditions


class TestValidateConditionDict:
    def test_accepts_a_wellformed_stackable_dict(self):
        c = {"type": "exhausted", "duration": None, "source": "forced_march", "stacks": 2}
        assert conditions.validate_condition_dict(c) is c

    def test_accepts_a_wellformed_hollowed_dict(self):
        c = {"type": "hollowed", "duration": None, "source": None, "stage": 1}
        assert conditions.validate_condition_dict(c) is c

    def test_rejects_unknown_type(self):
        with pytest.raises(ValueError, match="unknown condition type"):
            conditions.validate_condition_dict({"type": "bogus", "stacks": 1})

    def test_rejects_missing_type(self):
        with pytest.raises(ValueError, match="missing 'type'"):
            conditions.validate_condition_dict({"duration": None, "stacks": 1})

    def test_rejects_non_dict_entry(self):
        with pytest.raises(ValueError, match="not a dict"):
            conditions.validate_condition_dict(["exhausted"])

    def test_rejects_non_int_stacks(self):
        with pytest.raises(ValueError, match="stacks"):
            conditions.validate_condition_dict({"type": "exhausted", "stacks": "two"})

    def test_rejects_non_int_stage(self):
        with pytest.raises(ValueError, match="stage"):
            conditions.validate_condition_dict({"type": "hollowed", "stage": 1.5})

    def test_rejects_non_int_non_none_duration(self):
        with pytest.raises(ValueError, match="duration"):
            conditions.validate_condition_dict({"type": "stunned", "duration": "soon", "stacks": 1})

    def test_allows_absent_optional_fields(self):
        # stacks/stage/duration are validated only when present (well-formed dicts vary by type).
        c = {"type": "blinded"}
        assert conditions.validate_condition_dict(c) is c

    def test_validate_conditions_maps_over_list(self):
        good = [
            {"type": "exhausted", "stacks": 2},
            {"type": "hollowed", "stage": 1},
        ]
        assert conditions.validate_conditions(good) == good

    def test_validate_conditions_raises_on_any_corrupt_entry(self):
        with pytest.raises(ValueError, match="unknown condition type"):
            conditions.validate_conditions([{"type": "exhausted", "stacks": 1}, {"type": "bogus"}])


class TestReadPlayerConditionsValidation:
    """read_player_conditions runs the validator at the boundary: fail-loud on a corrupt stored
    row, validated passthrough on a good one. Validation is pure-Python post-fetch, so a mock conn
    exercises it (mirrors test_db_mutations_death's mock-conn unit tests)."""

    @pytest.mark.asyncio
    async def test_good_row_returns_validated_list(self):
        import db_mutations_conditions

        good = [{"type": "exhausted", "duration": None, "source": "march", "stacks": 2}]
        conn = AsyncMock()
        conn.fetchrow.return_value = {"conditions": good}
        out = await db_mutations_conditions.read_player_conditions("p1", conn=conn)
        assert out == good

    @pytest.mark.asyncio
    async def test_good_row_parses_json_string_then_validates(self):
        import db_mutations_conditions

        good = [{"type": "wounded", "duration": None, "source": None, "stacks": 1}]
        conn = AsyncMock()
        conn.fetchrow.return_value = {"conditions": json.dumps(good)}
        out = await db_mutations_conditions.read_player_conditions("p1", conn=conn)
        assert out == good

    @pytest.mark.asyncio
    async def test_corrupt_row_raises_fail_loud(self):
        import db_mutations_conditions

        conn = AsyncMock()
        conn.fetchrow.return_value = {"conditions": [{"type": "not_a_condition", "stacks": 1}]}
        with pytest.raises(ValueError, match="unknown condition type"):
            await db_mutations_conditions.read_player_conditions("p1", conn=conn)

    @pytest.mark.asyncio
    async def test_absent_row_returns_empty(self):
        import db_mutations_conditions

        conn = AsyncMock()
        conn.fetchrow.return_value = None
        assert await db_mutations_conditions.read_player_conditions("ghost", conn=conn) == []


class TestResolversTolerateJsonNullConditions:
    """M4.4 story-008 (concern 0f475c961261): players.data.conditions can be stored JSON null.
    A reader using ``get('conditions', [])`` gets ``None`` (the key IS present, just null) and
    crashes iterating it. Each condition-reading resolver must treat a null value as no conditions."""

    _ATTRS = {"strength": 12, "dexterity": 12, "constitution": 12, "wisdom": 12, "intelligence": 12, "charisma": 12}

    def test_resolve_skill_check_tolerates_null(self):
        from check_resolution import resolve_skill_check_dc

        player = {"attributes": self._ATTRS, "level": 3, "conditions": None}
        # No crash; returns a result (rng-free path is fine — we assert it doesn't raise).
        result = resolve_skill_check_dc(player, "athletics", 10)
        assert result is not None

    def test_resolve_saving_throw_tolerates_null(self):
        from check_resolution_save import resolve_saving_throw

        player = {"attributes": self._ATTRS, "level": 3, "conditions": None}
        result = resolve_saving_throw(player, "strength", 10, "knocked_prone")
        assert result is not None

    def test_resolve_attack_tolerates_null(self):
        from check_resolution_attack import resolve_attack

        attacker = {"attributes": self._ATTRS, "level": 3, "conditions": None}
        weapon = {"name": "Club", "damage": "1d4", "damage_type": "bludgeoning"}
        result = resolve_attack(attacker, weapon, target_ac=10, target_hp=10)
        assert result is not None
