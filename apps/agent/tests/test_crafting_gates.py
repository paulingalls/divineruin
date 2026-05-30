"""Tests for the shared crafting gate predicates (crafting_gates.py).

These two pure predicates are the single definition of the workspace-access and
tainted-Expert checks, consumed by both the pre-flight pipeline (creation) and
resolve_crafting (resolution). Exhaustive because they gate real crafting.
"""

import pytest

from crafting_gates import tainted_blocks_crafter, workspace_accessible


class TestWorkspaceAccessible:
    def test_required_in_accessible_passes(self):
        assert workspace_accessible("forge", ["field", "forge"]) is True

    def test_required_absent_fails(self):
        assert workspace_accessible("forge", ["field", "workshop"]) is False

    def test_exact_type_not_rank(self):
        # A laboratory must NOT satisfy a forge recipe even though they share a
        # basic-vs-advanced rank — access is exact-type (workspace-check3-access).
        assert workspace_accessible("forge", ["field", "laboratory"]) is False

    def test_field_floor(self):
        assert workspace_accessible("field", ["field"]) is True

    def test_empty_access_fails(self):
        assert workspace_accessible("forge", []) is False

    def test_unknown_required_workspace_fails_loud(self):
        with pytest.raises(ValueError):
            workspace_accessible("dungeon", ["field", "forge"])

    def test_accepts_any_iterable(self):
        assert workspace_accessible("forge", {"field", "forge"}) is True


class TestTaintedBlocksCrafter:
    def test_tainted_sub_expert_blocked(self):
        assert tainted_blocks_crafter("trained", True) is True
        assert tainted_blocks_crafter("untrained", True) is True

    def test_tainted_expert_allowed(self):
        assert tainted_blocks_crafter("expert", True) is False
        assert tainted_blocks_crafter("master", True) is False

    def test_untainted_never_blocks(self):
        # Not tainted → never blocked, regardless of tier.
        assert tainted_blocks_crafter("untrained", False) is False
        assert tainted_blocks_crafter("master", False) is False

    def test_untainted_skips_tier_validation(self):
        # Mirrors Check 5's short-circuit: tier is only examined when tainted.
        assert tainted_blocks_crafter("not_a_tier", False) is False

    def test_tainted_unknown_tier_fails_loud(self):
        with pytest.raises(ValueError):
            tainted_blocks_crafter("not_a_tier", True)
