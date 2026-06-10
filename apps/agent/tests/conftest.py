"""Shared test fixtures — auto-mock agent factories, seed training config."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _db_lifecycle import ensure_db_up, stop_if_started
from archetype_abilities_config_fixture import setup_archetype_abilities_config_fixture
from archetype_milestones_config_fixture import setup_archetype_milestones_config_fixture
from archetypes_config_fixture import setup_archetypes_config_fixture
from companion_profiles_config_fixture import setup_companion_profiles_config_fixture
from mentor_variants_config_fixture import setup_mentor_variants_config_fixture
from npcs_config_fixture import setup_npcs_config_fixture
from role_archetypes_config_fixture import setup_role_archetypes_config_fixture
from settlement_templates_config_fixture import setup_settlement_templates_config_fixture
from spells_config_fixture import setup_spells_config_fixture
from training_config_fixture import setup_training_config_fixture

# Tracks whether THIS process started docker compose, so sessionfinish only
# stops what sessionstart started.
_started_db = False


def _is_xdist_worker(config: pytest.Config) -> bool:
    """True on an xdist worker subprocess; False on the controller / serial run."""
    return hasattr(config, "workerinput")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Start the docker-compose dev DB for the run if it isn't already up.

    Many non-acceptance tests connect to the dev Postgres at :55432, so a bare
    `pytest` would fail when docker isn't running. ensure_db_up() is a fast
    no-op when the DB is already reachable (the common dev case) and only starts
    docker compose when it's down. See _db_lifecycle.py.

    Under pytest-xdist (-n N) every worker runs its own session; gating on the
    controller (no `workerinput`) ensures docker is started/stopped exactly once
    so a worker that finishes early can't stop the DB while others still query.
    """
    global _started_db
    if _is_xdist_worker(session.config):
        return
    _started_db = ensure_db_up()


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Stop docker compose iff this run started it (never `down -v`).

    Runs only on the controller / serial run, mirroring pytest_sessionstart, so
    the dev DB is preserved and workers never tear it down mid-run.
    """
    if _is_xdist_worker(session.config):
        return
    stop_if_started(_started_db)


@pytest.fixture(autouse=True)
def mock_combat_agent_factory():
    """Prevent real CombatAgent construction via start_combat in tests.

    CombatAgent inherits LiveKit Agent lifecycle methods that create
    unawaited coroutines during GC in test contexts. Mocking the factory
    avoids this while still testing the tool logic.
    """
    with patch("combat_agent.create_combat_agent", return_value=MagicMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def seed_training_config():
    """Populate training_rules._activity_types from content JSON before every test.

    Mirrors what load_training_activity_types() does at worker startup in
    production, but sync and file-based. Runs before each test so tests can
    freely call set_training_activity_types() to override without polluting
    other tests.
    """
    setup_training_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_archetypes():
    """Populate archetypes._archetypes from content/archetypes.json before every test.

    Mirrors load_archetypes() at worker startup, but sync and file-based, so
    chassis-fed math (calculate_max_hp, calculate_max_pools) resolves without a DB.
    """
    setup_archetypes_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_abilities():
    """Populate abilities._abilities from content/archetype_abilities.json before every test.

    Mirrors load_abilities() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_abilities() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_archetype_abilities_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_spells():
    """Populate spells._spells from content/spells.json before every test.

    Mirrors load_spells() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_spells() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_spells_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_mentor_variants():
    """Populate mentor_variants._mentor_variants from content before every test.

    Mirrors load_mentor_variants() at worker/agent startup, but sync and
    file-based. Required so agent.py dm_session's guarded load_mentor_variants()
    sees the map already populated (is_loaded() True) and skips the DB fetch in
    tests that exercise startup.
    """
    setup_mentor_variants_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_role_archetypes():
    """Populate role_archetypes._role_archetypes from content before every test.

    Mirrors load_role_archetypes() at worker/agent startup, but sync and file-based.
    Required so agent.py / async_worker.py's guarded load_role_archetypes() sees the map
    already populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_role_archetypes_config_fixture()
    yield


@pytest.fixture(autouse=True)
def stub_companion_affinity_io():
    """Default-stub the companion-relationship DB calls the errand path makes (M6.4 / story-003).

    errand_tools and async_worker call companion_relationship_queries.cached_effective_rank (the
    bonus rank) and .apply_errand_affinity (the persisted nudge); agent.py/onboarding_tools call
    .hydrate_companion_state at session start — all hit the DB. Stub them so session/errand/worker
    unit tests stay DB-free. tests/companion/test_relationship_persistence.py overrides this fixture
    (same name) to exercise the real read-modify-write against a fake conn.
    """
    from session_data import CompanionState

    async def _fake_hydrate(player_id, companion_id, name, *, conn=None):
        return CompanionState(id=companion_id, name=name, session_count=1)

    with (
        patch(
            "companion_relationship_queries.cached_effective_rank",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "companion_relationship_queries.apply_errand_affinity",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "companion_relationship_queries.hydrate_companion_state",
            side_effect=_fake_hydrate,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def seed_companion_profiles():
    """Populate companion_profiles._companion_profiles from content/companions.json before every test.

    Mirrors load_companion_profiles() at agent startup, but sync and file-based. Required so
    agent.py's guarded load_companion_profiles() sees the catalog already populated
    (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_companion_profiles_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_settlement_templates():
    """Populate settlement_templates._tiers/._personalities from content before every test.

    Mirrors load_settlement_templates() at agent startup, but sync and file-based. Required
    so agent.py's guarded load_settlement_templates() sees the catalog already populated
    (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_settlement_templates_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_npcs():
    """Populate npcs._npcs from content/npcs.json before every test.

    Mirrors load_npcs() at worker/agent startup, but sync and file-based. Required so
    agent.py / async_worker.py's guarded load_npcs() sees the map already populated
    (is_loaded() True) and skips the DB fetch in tests that exercise startup, and so
    the consolidated narration shims resolve NPC personas via get_npc_sync().
    """
    setup_npcs_config_fixture()
    yield


@pytest.fixture(autouse=True)
def seed_milestones():
    """Populate milestones._milestones from content/archetype_milestones.json before every test.

    Mirrors load_milestones() at worker/agent startup, but sync and file-based.
    Required so agent.py dm_session's guarded load_milestones() sees the map already
    populated (is_loaded() True) and skips the DB fetch in tests that exercise startup.
    """
    setup_archetype_milestones_config_fixture()
    yield
