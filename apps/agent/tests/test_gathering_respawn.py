"""Tests for the pure node-respawn resolver (M16, story-001).

Zero IO / zero RNG — offline unit tests covering each respawn class, the due-boundary,
already-full no-op, partial-quantity restore, and the fail-loud guards.
"""

import pytest

from gathering_respawn import NodeRespawn, compute_node_respawn


class TestFixedCadenceRespawn:
    def test_restores_to_capacity_when_elapsed_meets_respawn_days(self):
        result = compute_node_respawn(quantity=0, capacity=3, respawn_days=2, elapsed_days=2)
        assert result == NodeRespawn(new_quantity=3, restored=True)

    def test_restores_when_elapsed_exceeds_respawn_days(self):
        result = compute_node_respawn(quantity=1, capacity=3, respawn_days=2, elapsed_days=5)
        assert result == NodeRespawn(new_quantity=3, restored=True)

    def test_no_op_when_elapsed_is_short_of_respawn_days(self):
        result = compute_node_respawn(quantity=1, capacity=3, respawn_days=2, elapsed_days=1.9)
        assert result == NodeRespawn(new_quantity=1, restored=False)

    def test_no_op_when_already_at_capacity(self):
        result = compute_node_respawn(quantity=3, capacity=3, respawn_days=2, elapsed_days=10)
        assert result == NodeRespawn(new_quantity=3, restored=False)

    def test_no_op_when_above_capacity(self):
        result = compute_node_respawn(quantity=4, capacity=3, respawn_days=2, elapsed_days=10)
        assert result == NodeRespawn(new_quantity=4, restored=False)


class TestOneTimeNode:
    def test_never_restores_regardless_of_elapsed_time(self):
        result = compute_node_respawn(quantity=0, capacity=2, respawn_days=0, elapsed_days=1000)
        assert result == NodeRespawn(new_quantity=0, restored=False)


class TestPersistentNode:
    def test_treated_as_never_depleting_no_op(self):
        result = compute_node_respawn(quantity=1, capacity=4, respawn_days=-1, elapsed_days=1000)
        assert result == NodeRespawn(new_quantity=1, restored=False)


class TestFailLoudGuards:
    def test_raises_on_negative_elapsed_days(self):
        with pytest.raises(ValueError):
            compute_node_respawn(quantity=0, capacity=3, respawn_days=2, elapsed_days=-1)

    def test_raises_on_negative_capacity(self):
        with pytest.raises(ValueError):
            compute_node_respawn(quantity=0, capacity=-1, respawn_days=2, elapsed_days=5)
