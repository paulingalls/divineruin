"""Shared fixtures for the combat test suite.

The dev_db_pool real-PG fixture was promoted to the parent tests/conftest.py so the whole
fast lane can share it (combat persistence + db_mutations_death round-trip); parent-conftest
fixtures inherit down to this suite unchanged.

``default_condition_persistence`` (autouse) gives combat-end unit tests a safe empty-store default
for the player-condition read/save combat_end now performs on every teardown (concern ab37d4fc61c6);
real-PG tests (dev_db_pool) and tests with their own monkeypatch override it. Defined once in
tests/_combat_end_fixtures so the combat / handoff / durability suites share one copy.
"""

from _combat_end_fixtures import (  # noqa: F401  (autouse fixtures)
    default_condition_persistence,
    default_player_row,
)
