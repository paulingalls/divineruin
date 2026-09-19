import copy
import json
import platform
from pathlib import Path

import pytest

import dependency_upgrade_report
from dependency_upgrade_report import EnvironmentSnapshot, validate_report

ROOT = Path(__file__).resolve().parents[4]


def _report() -> dict:
    return json.loads((ROOT / "docs/dependency_upgrade.json").read_text())


def _snapshots(report: dict) -> dict[str, EnvironmentSnapshot]:
    versions: dict[str, dict[str, str]] = {}
    for row in report["dependencies"]:
        versions.setdefault(row["project"], {})[row["name"]] = row["installed"]
    snapshots = {
        project: EnvironmentSnapshot(
            prefix=str(ROOT / project / ".venv"),
            python_version=platform.python_version(),
            versions=project_versions,
            requirements={"livekit-plugins-anthropic": ["anthropic<1,>=0.41"]},
        )
        for project, project_versions in versions.items()
    }
    return snapshots


def test_wrong_recorded_python_version_fails():
    report = _report()
    snapshots = _snapshots(report)
    report["python_version"] = "0.0.0"

    with pytest.raises(ValueError, match=r"recorded Python 0.0.0.*environment Python"):
        validate_report(root=ROOT, report=report, snapshots=snapshots)


def test_wrong_recorded_uv_version_fails(monkeypatch):
    report = _report()
    snapshots = _snapshots(report)
    monkeypatch.setattr(dependency_upgrade_report, "current_uv_version", lambda: "0.0.0", raising=False)

    with pytest.raises(ValueError, match=rf"recorded uv {report['uv_version']}.*current uv 0.0.0"):
        validate_report(root=ROOT, report=report, snapshots=snapshots)


def test_malformed_registry_snapshot_date_fails():
    report = _report()
    snapshots = _snapshots(report)
    report["registry_snapshot_date"] = "September 18"

    with pytest.raises(ValueError, match="registry snapshot date must be ISO 8601"):
        validate_report(root=ROOT, report=report, snapshots=snapshots)


def test_scripts_python_mismatch_names_project():
    report = _report()
    snapshots = _snapshots(report)
    snapshots["scripts"] = copy.deepcopy(snapshots["scripts"])
    snapshots["scripts"].python_version = "0.0.0"

    with pytest.raises(ValueError, match=r"scripts.*environment Python 0.0.0"):
        validate_report(root=ROOT, report=report, snapshots=snapshots)
