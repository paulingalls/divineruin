import copy
import json
import shutil
from pathlib import Path

import pytest

from dependency_upgrade_report import validate_infrastructure_holds, validate_outcomes
from e2e_dependency_report import probe_installed, validate_e2e_report

ROOT = Path(__file__).resolve().parents[4]


def _report(root: Path) -> dict:
    return json.loads((root / "docs/dependency_upgrade.json").read_text())


def _copy_scope(tmp_path: Path) -> Path:
    for relative in ("e2e/package.json", "e2e/bun.lock", "docs/dependency_upgrade.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def _recorded_installed(report: dict) -> dict[str, str]:
    return {row["name"]: row["installed"] for row in report["e2e_dependencies"]}


def _validate(root: Path, report: dict | None = None) -> dict:
    selected = report or _report(root)
    validate_e2e_report(root, selected, _recorded_installed(selected))
    return selected


def test_checked_in_e2e_report_covers_manifest_lock_and_installed_tree():
    report = _report(ROOT)
    validate_e2e_report(ROOT, report, probe_installed(ROOT, report))
    assert report["e2e_dependencies"]


@pytest.mark.parametrize("relative", ["e2e/package.json", "e2e/bun.lock"])
def test_missing_e2e_input_fails(tmp_path, relative):
    root = _copy_scope(tmp_path)
    (root / relative).unlink()
    with pytest.raises(ValueError, match="missing"):
        _validate(root)


def test_empty_e2e_manifest_and_missing_row_fail(tmp_path):
    root = _copy_scope(tmp_path)
    manifest = json.loads((root / "e2e/package.json").read_text())
    manifest["devDependencies"] = {}
    (root / "e2e/package.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="e2e manifest dependency corpus is empty"):
        _validate(root)

    root = _copy_scope(tmp_path / "row")
    report = _report(root)
    removed = report["e2e_dependencies"].pop()
    with pytest.raises(ValueError, match=rf"missing e2e dependency row.*{removed['name']}"):
        _validate(root, report)


@pytest.mark.parametrize("field", ["requested", "locked", "installed"])
def test_wrong_e2e_version_fails(tmp_path, field):
    root = _copy_scope(tmp_path)
    report = _report(root)
    installed = _recorded_installed(report)
    row = report["e2e_dependencies"][0]
    row[field] = "0.0.0"
    with pytest.raises(ValueError, match=field):
        validate_e2e_report(root, report, installed)


def test_duplicate_and_surplus_e2e_rows_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    report["e2e_dependencies"].append(copy.deepcopy(report["e2e_dependencies"][0]))
    with pytest.raises(ValueError, match="duplicate e2e dependency row"):
        _validate(root, report)

    report = _report(root)
    extra = copy.deepcopy(report["e2e_dependencies"][0])
    extra["name"] = "surplus-package"
    report["e2e_dependencies"].append(extra)
    with pytest.raises(ValueError, match="surplus e2e dependency row"):
        _validate(root, report)


def test_stale_e2e_exclusion_fails(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    report["exclusions"] = {"e2e": "deferred"}
    with pytest.raises(ValueError, match="stale e2e exclusion"):
        _validate(root, report)


def test_historical_validation_record_covers_every_required_lane():
    validate_outcomes(_report(ROOT))


def test_missing_validation_outcome_fails():
    report = _report(ROOT)
    report["validation_outcomes"].pop(0)
    with pytest.raises(ValueError, match="historical validation outcome"):
        validate_outcomes(report)


@pytest.mark.parametrize(
    ("path", "value", "diagnostic"),
    [
        (("kind",), "current-execution-record", "marker"),
        (("accepted_commit",), "not-a-commit", "commit"),
        (("accepted_at",), "", "timestamp"),
    ],
)
def test_historical_validation_record_requires_an_acceptance_marker(path, value, diagnostic):
    report = _report(ROOT)
    target = report["evidence_record"]
    target[path[0]] = value
    with pytest.raises(ValueError, match=diagnostic):
        validate_outcomes(report)


def test_historical_outcomes_are_not_current_pass_requirements():
    report = _report(ROOT)
    report["validation_outcomes"][0]["status"] = "recorded failure"
    validate_outcomes(report)


def test_recorded_infrastructure_holds_are_declared_compose_images():
    validate_infrastructure_holds(ROOT, _report(ROOT))


def test_missing_compose_file_fails(tmp_path):
    with pytest.raises(ValueError, match="missing compose file"):
        validate_infrastructure_holds(tmp_path, _report(ROOT))


@pytest.mark.parametrize(
    ("mutate", "diagnostic"),
    [
        (lambda report: report["infrastructure_holds"].clear(), "infrastructure hold corpus is empty"),
        (lambda report: report["infrastructure_holds"][0].update(reason=""), "infrastructure hold reason is empty"),
        (
            lambda report: report["infrastructure_holds"][0].update(reference="postgres:18-alpine"),
            "not a declared compose image",
        ),
    ],
)
def test_stale_or_incomplete_infrastructure_holds_fail(mutate, diagnostic):
    report = _report(ROOT)
    mutate(report)
    with pytest.raises(ValueError, match=diagnostic):
        validate_infrastructure_holds(ROOT, report)
