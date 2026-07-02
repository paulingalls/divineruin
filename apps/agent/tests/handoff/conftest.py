"""Shared fixtures for the handoff test suite.

``default_condition_persistence`` (autouse) gives the end_combat handoff/roundtrip unit tests a safe
empty-store default for the player-condition read/save combat_end performs on every teardown (concern
ab37d4fc61c6). Defined once in tests/_combat_end_fixtures and shared across combat / handoff / durability.
"""

from _combat_end_fixtures import default_condition_persistence  # noqa: F401  (autouse fixture)
