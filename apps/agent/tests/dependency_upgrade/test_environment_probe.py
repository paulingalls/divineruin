import os
import sys
from pathlib import Path

import pytest

from dependency_upgrade_report import probe_environment

ROOT = Path(__file__).resolve().parents[4]


def test_missing_environment_fails_loud(tmp_path):
    with pytest.raises(ValueError, match="environment interpreter does not exist"):
        probe_environment(tmp_path / "missing-python", ["asyncpg"])


def test_missing_installed_package_fails_loud():
    with pytest.raises(ValueError, match=r"installed package is missing.*definitely-not-installed"):
        probe_environment(Path(sys.executable), ["definitely-not-installed"])


def test_probe_ignores_ambient_pythonpath(tmp_path, monkeypatch):
    dist_info = tmp_path / "anthropic-999.0.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: anthropic\nVersion: 999.0.0\n")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PYTHONHOME", os.environ.get("PYTHONHOME", ""))

    snapshot = probe_environment(ROOT / "apps/agent/.venv/bin/python", ["anthropic"])

    assert snapshot.versions["anthropic"] != "999.0.0"
