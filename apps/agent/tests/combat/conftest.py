"""Shared fixtures for the combat test suite.

The dev_db_pool real-PG fixture was promoted to the parent tests/conftest.py so the whole
fast lane can share it (combat persistence + db_mutations_death round-trip); parent-conftest
fixtures inherit down to this suite unchanged.
"""
