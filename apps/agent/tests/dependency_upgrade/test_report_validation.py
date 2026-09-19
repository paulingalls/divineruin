import copy
import json
import platform
import re
import shutil
from importlib import metadata
from pathlib import Path

import pytest

from dependency_upgrade_report import (
    EnvironmentSnapshot,
    render_markdown,
    validate_markdown,
    validate_report,
)

ROOT = Path(__file__).resolve().parents[4]


def _copy_scope(tmp_path: Path) -> Path:
    for relative in (
        "apps/agent/pyproject.toml",
        "apps/agent/uv.lock",
        "scripts/pyproject.toml",
        "scripts/uv.lock",
        "docs/dependency_upgrade.json",
        "docs/dependency_upgrade.md",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    return tmp_path


def _published_requirements() -> list[str]:
    """The vendor's own published constraint, never a hand-written copy of it."""
    return metadata.distribution("livekit-plugins-anthropic").requires or []


def _row(report: dict, name: str) -> dict:
    return next(row for row in report["dependencies"] if row["name"] == name)


def _load_report(root: Path) -> dict:
    return json.loads((root / "docs/dependency_upgrade.json").read_text())


def _snapshots(report: dict, root: Path) -> dict[str, EnvironmentSnapshot]:
    versions: dict[str, dict[str, str]] = {}
    for row in report["dependencies"]:
        versions.setdefault(row["project"], {})[row["name"]] = row["installed"]
    return {
        project: EnvironmentSnapshot(
            prefix=str(root / project / ".venv"),
            python_version=platform.python_version(),
            versions=project_versions,
            requirements={"livekit-plugins-anthropic": _published_requirements()},
        )
        for project, project_versions in versions.items()
    }


def _validate(root: Path) -> dict:
    report = _load_report(root)
    validate_report(root=root, report=report, snapshots=_snapshots(report, root))
    validate_markdown(root, report)
    return report


def test_checked_in_report_covers_manifests_locks_and_markdown():
    report = _validate(ROOT)

    assert report["projects"] == ["apps/agent", "scripts"]
    assert report["dependencies"]
    assert render_markdown(report) == (ROOT / "docs/dependency_upgrade.md").read_text()


@pytest.mark.parametrize(
    ("missing", "message"),
    (
        ("apps/agent/pyproject.toml", "missing manifest: apps/agent/pyproject.toml"),
        ("scripts/uv.lock", "missing lock: scripts/uv.lock"),
    ),
)
def test_missing_manifest_or_lock_fails_after_green_baseline(tmp_path, missing, message):
    root = _copy_scope(tmp_path)
    _validate(root)
    (root / missing).unlink()

    with pytest.raises(ValueError, match=message):
        _validate(root)


def test_missing_dependency_row_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    removed = report["dependencies"].pop()
    (root / "docs/dependency_upgrade.json").write_text(json.dumps(report))

    with pytest.raises(ValueError, match=f"missing dependency row.*{removed['name']}"):
        _validate(root)


def test_empty_corpus_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["dependencies"] = []
    (root / "docs/dependency_upgrade.json").write_text(json.dumps(report))

    with pytest.raises(ValueError, match="dependency corpus is empty"):
        _validate(root)


def test_surplus_report_row_and_unreported_manifest_dependency_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["dependencies"].append({**report["dependencies"][0], "name": "surplus"})
    (root / "docs/dependency_upgrade.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match=r"surplus dependency row.*surplus"):
        _validate(root)

    root = _copy_scope(tmp_path / "missing")
    manifest = root / "scripts/pyproject.toml"
    manifest.write_text(manifest.read_text().replace('"asyncpg>=0.31.0",', '"asyncpg>=0.31.0",\n    "httpx>=0.28.1",'))
    with pytest.raises(ValueError, match=r"missing dependency row.*httpx"):
        _validate(root)


def test_wrong_resolution_names_report_and_lock(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["dependencies"][0]["resolved"] = "0.0.0"
    snapshots = _snapshots(_load_report(root), root)

    with pytest.raises(ValueError, match=r"report resolution.*lock resolution"):
        validate_report(root=root, report=report, snapshots=snapshots)


@pytest.mark.parametrize("field", ["reason", "specifier"])
def test_empty_anthropic_holdback_field_fails(tmp_path, field):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    row = _row(report, "anthropic")
    row["held_back_by"][field] = ""

    with pytest.raises(ValueError, match=f"held_back_by.{field}"):
        validate_report(root=root, report=report, snapshots=_snapshots(report, root))


def test_wrong_nonempty_vendor_constraint_fails(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    row = _row(report, "anthropic")
    row["held_back_by"]["specifier"] = "<2,>=0.41"

    with pytest.raises(ValueError, match=r"vendor metadata.*anthropic<1,>=0.41"):
        validate_report(root=root, report=report, snapshots=_snapshots(report, root))


def test_installed_version_mismatch_names_project_and_versions(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    snapshots = _snapshots(report, root)
    snapshots["scripts"] = copy.deepcopy(snapshots["scripts"])
    snapshots["scripts"].versions["asyncpg"] = "0.0.0"

    with pytest.raises(ValueError, match=r"scripts.*asyncpg.*installed 0.0.0.*locked 0.31.0"):
        validate_report(root=root, report=report, snapshots=snapshots)


def test_shared_environment_prefix_fails(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    snapshots = _snapshots(report, root)
    snapshots["scripts"] = copy.deepcopy(snapshots["scripts"])
    snapshots["scripts"].prefix = snapshots["apps/agent"].prefix

    with pytest.raises(ValueError, match="distinct environment prefixes"):
        validate_report(root=root, report=report, snapshots=snapshots)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("registry_snapshot_date", "", "report metadata is missing: registry_snapshot_date"),
        ("python_version", "", "report metadata is missing: python_version"),
        ("uv_version", "", "report metadata is missing: uv_version"),
        ("projects", ["apps/agent"], "report projects must be"),
    ),
)
def test_missing_report_metadata_fails_after_green_baseline(tmp_path, field, value, message):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    snapshots = _snapshots(report, root)
    report[field] = value

    with pytest.raises(ValueError, match=message):
        validate_report(root=root, report=report, snapshots=snapshots)


def test_empty_latest_stable_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    snapshots = _snapshots(report, root)
    report["dependencies"][0]["latest_stable"] = ""

    with pytest.raises(ValueError, match=r"latest stable version is empty.*livekit-agents"):
        validate_report(root=root, report=report, snapshots=snapshots)


def test_optional_dependency_group_fails_rather_than_going_unwalked(tmp_path):
    root = _copy_scope(tmp_path)
    _validate(root)
    manifest = root / "scripts/pyproject.toml"
    manifest.write_text(manifest.read_text() + '\n[project.optional-dependencies]\nextra = ["httpx>=0.28.1"]\n')

    with pytest.raises(ValueError, match=r"unwalked optional dependencies: scripts/extra"):
        _validate(root)


@pytest.mark.parametrize(
    ("name", "path", "value", "message"),
    (
        ("httpx", ("requested",), ">=0.0.1", r"requested specifier mismatch.*httpx"),
        ("httpx", ("installed",), "0.0.0", r"recorded installed version differs.*httpx"),
        (
            "httpx",
            ("held_back_by",),
            {"package": "livekit-agents", "version": "1.8.2", "specifier": "<1", "reason": "invented"},
            r"holdback recorded for current dependency.*httpx",
        ),
        ("anthropic", ("held_back_by",), None, r"held_back_by is required.*anthropic"),
        ("anthropic", ("held_back_by", "version"), "0.0.0", r"held-back vendor version differs.*anthropic"),
    ),
)
def test_report_row_defect_fails_after_green_baseline(tmp_path, name, path, value, message):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    snapshots = _snapshots(report, root)
    target = _row(report, name)
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        validate_report(root=root, report=report, snapshots=snapshots)


def test_duplicate_report_row_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["dependencies"].append(copy.deepcopy(_row(report, "httpx")))

    with pytest.raises(ValueError, match=r"duplicate report dependency row.*httpx"):
        validate_report(root=root, report=report, snapshots=_snapshots(report, root))


def test_duplicate_manifest_dependency_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    _validate(root)
    manifest = root / "scripts/pyproject.toml"
    manifest.write_text(
        manifest.read_text().replace('"asyncpg>=0.31.0",', '"asyncpg>=0.31.0",\n    "asyncpg>=0.31.0",')
    )

    with pytest.raises(ValueError, match=r"duplicate direct dependency: scripts/runtime/asyncpg"):
        _validate(root)


def test_empty_manifest_corpus_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    _validate(root)
    for project in ("apps/agent", "scripts"):
        manifest = root / project / "pyproject.toml"
        manifest.write_text(
            re.sub(r"(?ms)^dependencies = \[.*?^\]|^dev = \[.*?^\]", "dependencies = []", manifest.read_text())
        )

    with pytest.raises(ValueError, match="manifest dependency corpus is empty"):
        _validate(root)


def test_markdown_drift_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    _row(report, "anthropic")["held_back_by"]["reason"] = "a reason the committed markdown does not render"
    (root / "docs/dependency_upgrade.json").write_text(json.dumps(report))

    with pytest.raises(ValueError, match="rendered documentation mismatch"):
        _validate(root)


def test_missing_markdown_fails_after_green_baseline(tmp_path):
    root = _copy_scope(tmp_path)
    _validate(root)
    (root / "docs/dependency_upgrade.md").unlink()

    with pytest.raises(ValueError, match=re.escape("missing report: docs/dependency_upgrade.md")):
        _validate(root)
