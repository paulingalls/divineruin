import json
import shutil
from pathlib import Path

import pytest

from workspace_dependency_report import probe_installed, validate_workspace_report

ROOT = Path(__file__).resolve().parents[4]


def _report(root: Path) -> dict:
    return json.loads((root / "docs/dependency_upgrade.json").read_text())


def _copy_scope(tmp_path: Path) -> Path:
    paths = ["package.json", "bun.lock", "bunfig.toml", "docs/dependency_upgrade.json"]
    report = _report(ROOT)
    paths.extend(f"{project}/package.json" for project in report["workspace_projects"] if project != ".")
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def _recorded_installed(report: dict) -> dict[tuple[str, str], str]:
    return {(row["project"], row["name"]): row["installed"] for row in report["workspace_dependencies"]}


def _validate(root: Path, report: dict | None = None) -> dict:
    selected = report or _report(root)
    validate_workspace_report(root, selected, _recorded_installed(selected))
    return selected


def test_checked_in_workspace_report_covers_manifests_lock_and_installed_tree():
    report = _report(ROOT)
    validate_workspace_report(ROOT, report, probe_installed(ROOT, report))
    assert report["workspace_dependencies"]


def test_hoisted_git_dependency_uses_bun_provenance_tag(tmp_path):
    package = tmp_path / "apps/mobile/node_modules/example"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"name":"example","version":"1.0.0"}')
    (package / ".bun-tag").write_text("owner-example-abc1234")
    report = {
        "workspace_dependencies": [
            {
                "project": "apps/mobile",
                "name": "example",
                "locked": "github:owner/example#abc1234",
            }
        ]
    }

    assert probe_installed(tmp_path, report) == {("apps/mobile", "example"): "github:owner/example#abc1234"}

    (package / ".bun-tag").write_text("owner-example-wrong")
    with pytest.raises(ValueError, match="installed source differs from lock"):
        probe_installed(tmp_path, report)


def test_omitted_workspace_and_dependency_rows_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["workspace_projects"].pop()
    with pytest.raises(ValueError, match="missing workspace project"):
        _validate(root, report)

    report = _report(root)
    removed = report["workspace_dependencies"].pop()
    with pytest.raises(ValueError, match=f"missing workspace dependency row.*{removed['name']}"):
        _validate(root, report)


def test_missing_lock_and_empty_workspace_match_fail(tmp_path):
    root = _copy_scope(tmp_path)
    _validate(root)
    (root / "bun.lock").unlink()
    with pytest.raises(ValueError, match=r"missing lock: bun.lock"):
        _validate(root)

    root = _copy_scope(tmp_path / "empty")
    package = json.loads((root / "package.json").read_text())
    package["workspaces"] = ["missing/*"]
    (root / "package.json").write_text(json.dumps(package))
    with pytest.raises(ValueError, match="workspace manifest corpus is empty"):
        _validate(root)


def test_wrong_lock_and_installed_resolution_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    row = next(item for item in report["workspace_dependencies"] if item["locked"] != "workspace:*")
    row["locked"] = "0.0.0"
    with pytest.raises(ValueError, match=f"lock resolution.*{row['name']}"):
        _validate(root, report)

    report = _report(root)
    installed = _recorded_installed(report)
    key = next(iter(installed))
    installed[key] = "0.0.0"
    with pytest.raises(ValueError, match="installed resolution"):
        validate_workspace_report(root, report, installed)


@pytest.mark.parametrize("field", ["bun_version", "minimum_release_age"])
def test_missing_workspace_metadata_fails(tmp_path, field):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report[field] = None
    with pytest.raises(ValueError, match=field):
        _validate(root, report)


def test_wrong_runtime_policy_and_override_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["bun_version"] = "0.0.0"
    with pytest.raises(ValueError, match="running Bun"):
        _validate(root, report)

    report = _report(root)
    (root / "bunfig.toml").write_text("[install]\nminimumReleaseAge = 1\n")
    with pytest.raises(ValueError, match="minimum_release_age differs"):
        _validate(root, report)

    root = _copy_scope(tmp_path / "override")
    report = _validate(root)
    report["overrides"] = []
    with pytest.raises(ValueError, match="override inventory"):
        _validate(root, report)


@pytest.mark.parametrize("field", ["candidate", "registry_latest"])
def test_blank_candidate_or_registry_latest_fails(tmp_path, field):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    report["workspace_dependencies"][0][field] = ""
    with pytest.raises(ValueError, match=f"{field} is empty"):
        _validate(root, report)


def test_candidate_latest_difference_requires_reason(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    row = next(item for item in report["workspace_dependencies"] if item["candidate"] != item["registry_latest"])
    row["reason"] = ""
    with pytest.raises(ValueError, match=f"candidate difference requires reason.*{row['name']}"):
        _validate(root, report)


def test_mobile_react_and_e2e_exclusions_are_required(tmp_path):
    root = _copy_scope(tmp_path)
    report = _validate(root)
    mobile = next(item for item in report["workspace_dependencies"] if item["project"] == "apps/mobile")
    mobile["held_by"] = None
    with pytest.raises(ValueError, match=r"apps/mobile.*story 207/208"):
        _validate(root, report)

    report = _report(root)
    report["exclusions"].pop("e2e")
    with pytest.raises(ValueError, match=r"e2e.*story 210"):
        _validate(root, report)
