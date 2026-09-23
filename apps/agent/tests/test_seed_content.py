import contextlib
import sys
import traceback
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import seed_content  # type: ignore[import-not-found]  # noqa: E402


async def _connect_must_not_run(_database_url):
    pytest.fail("seed connected before refusing its target")


@pytest.mark.parametrize("database_url", [None, ""])
async def test_main_requires_nonempty_database_url(monkeypatch, database_url):
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(seed_content.asyncpg, "connect", _connect_must_not_run)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await seed_content.main()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql:///worktree_world",
        "postgresql://seed-db.example/worktree_world",
        "postgresql://seed-db.example:6543",
    ],
)
async def test_main_requires_explicit_target_components(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(seed_content.asyncpg, "connect", _connect_must_not_run)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await seed_content.main()


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("Xy7/rest", "Xy7"),
        ("Xy7#rest", "Xy7"),
        ("Xy7?rest", "Xy7"),
        ("Xy7[rest", "Xy7"),
        ("12345/rest", "12345"),
        ("12345/re?st", "12345"),
        ("12345/re#st", "12345"),
    ],
)
async def test_unencoded_password_refusal_does_not_echo_it(monkeypatch, capsys, password, fragment):
    monkeypatch.setenv("DATABASE_URL", f"postgresql://seed_operator:{password}@seed-db.example:6543/worktree_world")
    monkeypatch.setattr(seed_content.asyncpg, "connect", _connect_must_not_run)

    with pytest.raises(RuntimeError, match="DATABASE_URL") as refused:
        await seed_content.main()

    reported = "".join(traceback.format_exception(refused.value)) + capsys.readouterr().out
    assert fragment not in reported
    assert "rest" not in reported


async def test_main_prints_redacted_target_before_connect(monkeypatch, capsys):
    database_url = "postgresql://seed_operator:swordfish@seed-db.example:6543/worktree_world"
    monkeypatch.setenv("DATABASE_URL", database_url)

    class StopBeforeConnect(Exception):
        pass

    async def inspect_output_at_connect(actual_database_url):
        assert actual_database_url == database_url
        output = capsys.readouterr().out
        assert "host=seed-db.example" in output
        assert "port=6543" in output
        assert "database=worktree_world" in output
        assert "seed_operator" not in output
        assert "swordfish" not in output
        raise StopBeforeConnect

    monkeypatch.setattr(seed_content.asyncpg, "connect", inspect_output_at_connect)

    with pytest.raises(StopBeforeConnect):
        await seed_content.main()


async def test_success_names_target_and_closes_connection(monkeypatch, capsys):
    database_url = "postgresql://seed_operator:swordfish@seed-db.example:6543/worktree_world"
    monkeypatch.setenv("DATABASE_URL", database_url)

    class FakeConnection:
        def __init__(self):
            self.closed = False

        def transaction(self):
            return contextlib.nullcontext()

        async def close(self):
            self.closed = True

    connection = FakeConnection()

    async def connect(actual_database_url):
        assert actual_database_url == database_url
        return connection

    async def seed(_connection):
        return {"locations": 2, "npcs": 3}

    async def seed_map_progress(_connection):
        return None

    async def validate(_connection):
        return []

    monkeypatch.setattr(seed_content.asyncpg, "connect", connect)
    monkeypatch.setattr(seed_content, "seed", seed)
    monkeypatch.setattr(seed_content, "seed_map_progress", seed_map_progress)
    monkeypatch.setattr(seed_content, "validate", validate)

    await seed_content.main()

    done_line = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("Done:"))
    assert "host=seed-db.example" in done_line
    assert "port=6543" in done_line
    assert "database=worktree_world" in done_line
    assert connection.closed


def test_harnesses_do_not_claim_to_mirror_seed_default():
    stale_claim = "Mirrors scripts/" + "seed_content.py's default"
    paths = [
        _REPO_ROOT / "scripts" / "ensure-db.ts",
        _REPO_ROOT / "apps" / "agent" / "tests" / "_db_lifecycle.py",
    ]

    for path in paths:
        assert stale_claim not in path.read_text()
