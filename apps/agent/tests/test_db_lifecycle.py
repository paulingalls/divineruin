"""Unit tests for the test-session DB lifecycle helper (_db_lifecycle).

The helper lets a bare `pytest` run self-heal when the docker-compose Postgres
isn't up: it detects reachability, starts `docker compose` if needed, and stops
ONLY what it started (never `down -v`, so the canonical dev DB survives). These
tests pin the pure parse + the start/stop decision; the actual docker subprocess
calls are stubbed so the suite stays hermetic.
"""

import subprocess

import _db_lifecycle as dbl
import pytest

REAL_AUTHORIZE = dbl._authorize
REAL_AUTHORIZE_RUNTIME = dbl._authorize_runtime
REAL_OWNER_HELPER = dbl._OWNER_HELPER


def _owned_checkout(tmp_path, monkeypatch) -> dict[str, str]:
    """A disposable Git checkout whose .env the REAL authority accepts.

    The authority answers about the checkout it runs in, so a hardcoded
    "foreign" endpoint is only foreign from SOME checkouts: :55432/:56379 are
    the primary's OWN endpoints, and CI's runner has no repo-root .env at all.
    Generating the settings here makes owned-vs-foreign known rather than
    inherited from wherever the suite happens to run. Returns those settings.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    expected = subprocess.run(
        ["bash", str(REAL_OWNER_HELPER), "expected-env"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (root / ".env").write_text(expected)
    monkeypatch.setattr(dbl, "_REPO_ROOT", root)
    return dict(line.split("=", 1) for line in expected.splitlines())


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    """Every test gets its own lock/state dir so tests never see each
    other's (or a real dev run's) refcount state."""
    monkeypatch.setattr(dbl, "_temp_base_dir", lambda: tmp_path)
    monkeypatch.setattr(dbl, "_authorize", lambda intent: None)
    monkeypatch.setattr(dbl, "_authorize_runtime", lambda database_url, redis_url: None)


class _FakeCompleted:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


# ── DSN resolution (story-006) ────────────────────────────────────────────────
# A worktree's .env carries that worktree's offset DATABASE_URL, but `uv run`
# never LOADS .env (it only passes ambient env through), so a bare
# `cd apps/agent && uv run pytest` used to fall back to the hardcoded primary
# :55432 and read/write the WRONG checkout's database. These pin the precedence.


def _write_env(tmp_path, body: str):
    """Write a repo-root .env under tmp_path and point _db_lifecycle at it."""
    env_path = tmp_path / ".env"
    env_path.write_text(body)
    return env_path


def test_resolve_database_url_prefers_environment_over_env_file(tmp_path, monkeypatch):
    """A real env var wins: CI and the acceptance testcontainer both set one."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DATABASE_URL=postgresql://u:p@localhost:1111/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:2222/db")

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:2222/db"


def test_resolve_database_url_reads_env_file_when_environment_unset(tmp_path, monkeypatch):
    """The worktree case: no exported DSN, so .env decides — not the :55432 default."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DATABASE_URL=postgresql://u:p@localhost:63782/divineruin\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_strips_surrounding_quotes(tmp_path, monkeypatch):
    """This repo's .env quote-wraps its values; an unstripped quote yields a DSN
    asyncpg cannot parse (the same trap that 403s the Inworld key)."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, 'DATABASE_URL="postgresql://u:p@localhost:63782/divineruin"\n')
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_falls_back_to_default_without_env_file(tmp_path, monkeypatch):
    """No .env at all (a fresh clone) still resolves to the canonical dev DB."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == dbl._DEFAULT_DATABASE_URL


def test_stop_if_started_honours_the_dsn_captured_at_session_start(monkeypatch):
    """sessionstart and sessionfinish must decrement the SAME refcount.

    The acceptance lane's bdd fixture assigns os.environ["DATABASE_URL"] to its
    testcontainer and never restores it, so a re-resolve at sessionfinish would
    key the lock/state file on the testcontainer's host:port — leaking the dev
    DB's count forever and skipping its teardown. Passing the start-time DSN
    through pins the pair to one state file.
    """
    dev_dsn = "postgresql://u:p@localhost:55432/divineruin"
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 1, "harness_started": True})

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    # A leaked testcontainer DSN in the environment must not steer the teardown.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:49173/test")

    dbl.stop_if_started(True, dev_dsn)

    assert calls == [("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_ensure_db_up_honours_an_explicit_dsn_over_the_environment(monkeypatch):
    """The DSN sessionstart resolved wins, so the pair keys one host:port."""
    dev_dsn = "postgresql://u:p@localhost:55432/divineruin"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:49173/test")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)

    assert dbl.ensure_db_up(dev_dsn) is False

    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path)["count"] == 1


def test_resolve_database_url_ignores_comments_blanks_and_other_keys(tmp_path, monkeypatch):
    """A real .env is mostly other keys and prose comments."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(
        tmp_path,
        "# Postgres — see docs\n"
        "\n"
        "ANTHROPIC_API_KEY=sk-not-a-dsn\n"
        "DATABASE_URL=postgresql://u:p@localhost:63782/divineruin\n"
        "REDIS_URL=redis://localhost:63786\n",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_falls_back_when_env_file_lacks_the_key(tmp_path, monkeypatch):
    """A .env that never declares DATABASE_URL must not resolve to empty."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DEEPGRAM_API_KEY=abc\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == dbl._DEFAULT_DATABASE_URL


def test_ownership_is_checked_before_reachability(monkeypatch):
    events: list[str] = []

    def authorize_runtime(database_url, redis_url):
        events.append(f"authorize-runtime:{database_url}:{redis_url or ''}")

    def reachable(host, port, timeout=1.0):
        events.append("reachable")
        return True

    monkeypatch.setattr(dbl, "_authorize_runtime", authorize_runtime)
    monkeypatch.setattr(dbl, "_authorize", lambda intent: events.append(f"authorize:{intent}"))
    monkeypatch.setattr(dbl, "is_reachable", reachable)

    assert dbl.ensure_db_up("postgresql://u:p@localhost:55432/db") is False
    assert events == [
        "authorize-runtime:postgresql://u:p@localhost:55432/db:",
        "reachable",
        "authorize:reuse",
    ]


def test_ownership_refusal_prevents_reachability(monkeypatch):
    monkeypatch.setattr(
        dbl,
        "_authorize_runtime",
        lambda database_url, redis_url: (_ for _ in ()).throw(RuntimeError("foreign checkout owner")),
    )
    monkeypatch.setattr(
        dbl,
        "is_reachable",
        lambda *args: (_ for _ in ()).throw(AssertionError("reachability must not run")),
    )

    with pytest.raises(RuntimeError, match="foreign checkout owner"):
        dbl.ensure_db_up("postgresql://u:p@localhost:55432/db")


def test_real_authority_accepts_the_checkouts_own_endpoints(tmp_path, monkeypatch):
    """The floor under the two refusals below: this fixture is not a blanket no."""
    settings = _owned_checkout(tmp_path, monkeypatch)
    REAL_AUTHORIZE_RUNTIME(settings["DATABASE_URL"], settings["REDIS_URL"])


def test_real_authority_rejects_explicit_foreign_dsn_before_probe(tmp_path, monkeypatch):
    settings = _owned_checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(dbl, "_authorize_runtime", REAL_AUTHORIZE_RUNTIME)
    monkeypatch.setenv("REDIS_URL", settings["REDIS_URL"])
    monkeypatch.setattr(
        dbl,
        "is_reachable",
        lambda *args: (_ for _ in ()).throw(AssertionError("foreign endpoint was probed")),
    )
    foreign_port = int(settings["POSTGRES_HOST_PORT"]) + 1

    with pytest.raises(RuntimeError, match="runtime DATABASE_URL"):
        dbl.ensure_db_up(f"postgresql://u:p@localhost:{foreign_port}/divineruin")


def test_real_authority_rejects_foreign_redis_before_probe(tmp_path, monkeypatch):
    settings = _owned_checkout(tmp_path, monkeypatch)
    monkeypatch.setattr(dbl, "_authorize_runtime", REAL_AUTHORIZE_RUNTIME)
    monkeypatch.setenv("REDIS_URL", f"redis://localhost:{int(settings['VALKEY_HOST_PORT']) + 1}")
    monkeypatch.setattr(
        dbl,
        "is_reachable",
        lambda *args: (_ for _ in ()).throw(AssertionError("foreign endpoint was probed")),
    )

    with pytest.raises(RuntimeError, match="runtime REDIS_URL"):
        dbl.ensure_db_up(settings["DATABASE_URL"])


def test_readiness_raises_ownership_refusal_without_sleep(monkeypatch):
    result = _FakeCompleted(returncode=0)
    refusal = _FakeCompleted(returncode=78)
    refusal.stderr = "worktree ownership: project belongs to foreign checkout"
    calls = iter([result, refusal])
    monkeypatch.setattr(dbl, "_compose", lambda *args: next(calls))
    monkeypatch.setattr(
        dbl.time,
        "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("ownership refusal was retried")),
    )

    with pytest.raises(RuntimeError, match="foreign checkout"):
        dbl._start_compose("localhost", 55432, "divineruin")


def test_readiness_retries_plain_pg_isready_not_ready(monkeypatch):
    ready = _FakeCompleted(returncode=0)
    not_ready = _FakeCompleted(returncode=1)
    calls = iter([ready, not_ready, ready])
    sleeps = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: next(calls))
    monkeypatch.setattr(dbl.time, "sleep", lambda seconds: sleeps.append(seconds))

    dbl._start_compose("localhost", 55432, "divineruin")
    assert sleeps == [1]


def test_compose_runs_only_after_runtime_urls_are_authorized(monkeypatch):
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["env"])
        return _FakeCompleted()

    monkeypatch.setenv("DATABASE_URL", "postgresql://foreign@localhost:1/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:2")
    monkeypatch.setattr(dbl.subprocess, "run", run)

    dbl._compose("ps")
    assert "DATABASE_URL" not in captured
    assert "REDIS_URL" not in captured


def test_ci_service_mode_never_starts_compose(monkeypatch):
    events: list[str] = []
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("DIVINERUIN_CI_SERVICE_DB", "1")
    monkeypatch.setattr(dbl, "_authorize", lambda intent: events.append(f"authorize:{intent}"))
    monkeypatch.setattr(dbl, "is_reachable", lambda *args: False)
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("CI must not invoke Compose")),
    )

    with pytest.raises(RuntimeError, match="Compose mutation is disabled"):
        dbl.ensure_db_up("postgresql://u:p@localhost:55432/db")
    assert events == ["authorize:ci"]


def test_stop_rechecks_destroy_ownership_before_down(monkeypatch):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 1, "harness_started": True})
    monkeypatch.setattr(
        dbl,
        "_authorize",
        lambda intent: (_ for _ in ()).throw(RuntimeError("owner changed")),
    )
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("down must not run")),
    )

    with pytest.raises(RuntimeError, match="owner changed"):
        dbl.stop_if_started(True, "postgresql://u:p@localhost:55432/db")
