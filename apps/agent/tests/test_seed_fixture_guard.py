import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import seed_content  # type: ignore[import-not-found]  # noqa: E402


class StopAtConnect(Exception):
    pass


def set_seed_env(monkeypatch: pytest.MonkeyPatch, host: str, mode: str | None) -> str:
    database_url = f"postgresql://seed_operator:fixture-secret@{host}:6543/worktree_world"
    monkeypatch.setenv("DATABASE_URL", database_url)
    if mode is None:
        monkeypatch.delenv("SEED_PRODUCTION", raising=False)
    else:
        monkeypatch.setenv("SEED_PRODUCTION", mode)
    return database_url


async def stop_at_connect(_database_url: str) -> None:
    raise StopAtConnect


@pytest.mark.parametrize("host,mode", [("seed-db.example", None), ("localhost.example", None), ("seed-db.example", "")])
async def test_remote_seed_requires_explicit_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], host: str, mode: str | None
) -> None:
    set_seed_env(monkeypatch, host, mode)
    monkeypatch.setattr(seed_content.asyncpg, "connect", stop_at_connect)

    with pytest.raises(RuntimeError) as error:
        await seed_content.main()

    assert host in str(error.value)
    assert "SEED_PRODUCTION=1" in str(error.value)
    assert "SEED_PRODUCTION=0" in str(error.value)
    output = capsys.readouterr()
    diagnostic = f"{error.value}\n{output.out}\n{output.err}"
    assert "seed_operator" not in diagnostic
    assert "fixture-secret" not in diagnostic


@pytest.mark.parametrize(
    "host,mode",
    [
        ("seed-db.example", "0"),
        ("seed-db.example", "1"),
        ("localhost", None),
        ("127.0.0.1", None),
        ("[::1]", None),
        ("localhost", ""),
    ],
)
async def test_seed_connects_in_selected_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], host: str, mode: str | None
) -> None:
    database_url = set_seed_env(monkeypatch, host, mode)

    async def inspect_at_connect(actual_database_url: str) -> None:
        assert actual_database_url == database_url
        output = capsys.readouterr().out
        expected_mode = "production" if mode == "1" else "default (fixtures enabled)"
        assert f"Seed mode: {expected_mode}" in output
        assert f"Target database: host={host.strip('[]')} port=6543 database=worktree_world" in output
        assert "seed_operator" not in output
        assert "fixture-secret" not in output
        raise StopAtConnect

    monkeypatch.setattr(seed_content.asyncpg, "connect", inspect_at_connect)
    with pytest.raises(StopAtConnect):
        await seed_content.main()


@pytest.mark.parametrize("mode", ["true", "false", "2", " 0", "1 "])
async def test_invalid_seed_mode_names_accepted_values(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    set_seed_env(monkeypatch, "localhost", mode)
    monkeypatch.setattr(seed_content.asyncpg, "connect", stop_at_connect)

    with pytest.raises(ValueError) as error:
        await seed_content.main()

    assert "SEED_PRODUCTION=1" in str(error.value)
    assert "SEED_PRODUCTION=0" in str(error.value)
