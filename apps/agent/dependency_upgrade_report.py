import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ci_toolchain_validation import validate_ci_toolchain
from dependency_report_render import render_markdown
from e2e_dependency_report import probe_installed as probe_e2e_installed
from e2e_dependency_report import validate_e2e_report
from workspace_dependency_report import probe_installed as probe_workspace_installed
from workspace_dependency_report import validate_workspace_report

PROJECTS = ("apps/agent", "scripts")
NAME_RE = re.compile(r"[-_.]+")
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$")


@dataclass
class EnvironmentSnapshot:
    prefix: str
    python_version: str
    versions: dict[str, str]
    requirements: dict[str, list[str]]


def normalize_name(name: str) -> str:
    return NAME_RE.sub("-", name).lower()


def split_requirement(requirement: str) -> tuple[str, str]:
    match = REQUIREMENT_RE.match(requirement)
    if not match:
        raise ValueError(f"invalid direct requirement: {requirement}")
    return normalize_name(match.group(1)), match.group(2).strip()


def manifest_rows(root: Path) -> dict[tuple[str, str, str], str]:
    rows: dict[tuple[str, str, str], str] = {}
    for project in PROJECTS:
        path = root / project / "pyproject.toml"
        if not path.is_file():
            raise ValueError(f"missing manifest: {path.relative_to(root)}")
        manifest = tomllib.loads(path.read_text())
        optional = manifest.get("project", {}).get("optional-dependencies", {})
        if optional:
            raise ValueError(f"unwalked optional dependencies: {project}/{', '.join(sorted(optional))}")
        groups = {"runtime": manifest.get("project", {}).get("dependencies", [])}
        groups.update(manifest.get("dependency-groups", {}))
        for group, requirements in groups.items():
            for requirement in requirements:
                name, requested = split_requirement(requirement)
                key = (project, group, name)
                if key in rows:
                    raise ValueError(f"duplicate direct dependency: {project}/{group}/{name}")
                rows[key] = requested
    if not rows:
        raise ValueError("manifest dependency corpus is empty")
    return rows


def lock_versions(root: Path) -> dict[str, dict[str, str]]:
    locks: dict[str, dict[str, str]] = {}
    for project in PROJECTS:
        path = root / project / "uv.lock"
        if not path.is_file():
            raise ValueError(f"missing lock: {path.relative_to(root)}")
        packages: dict[str, set[str]] = {}
        for package in tomllib.loads(path.read_text()).get("package", []):
            packages.setdefault(normalize_name(package["name"]), set()).add(package["version"])
        locks[project] = {}
        for name, versions in packages.items():
            if len(versions) == 1:
                locks[project][name] = next(iter(versions))
    return locks


def probe_environment(interpreter: Path, packages: list[str]) -> EnvironmentSnapshot:
    if not interpreter.is_file():
        raise ValueError(f"environment interpreter does not exist: {interpreter}")
    probe = """
import importlib.metadata as m, json, platform, re, sys
norm=lambda value: re.sub(r"[-_.]+", "-", value).lower()
versions={}
requirements={}
missing=[]
for requested in sys.argv[1:]:
    try:
        distribution=m.distribution(requested)
    except m.PackageNotFoundError:
        missing.append(requested)
        continue
    name=norm(distribution.metadata["Name"])
    versions[name]=distribution.version
    requirements[name]=distribution.requires or []
print(json.dumps({"prefix": sys.prefix, "python_version": platform.python_version(), "versions": versions, "requirements": requirements, "missing": missing}))
"""
    result = subprocess.run(
        [str(interpreter), "-I", "-c", probe, *packages],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if payload["missing"]:
        raise ValueError(f"installed package is missing: {', '.join(payload['missing'])}")
    return EnvironmentSnapshot(
        payload["prefix"], payload["python_version"], payload["versions"], payload["requirements"]
    )


def probe_scope(root: Path, environment_paths: dict[str, Path] | None = None) -> dict[str, EnvironmentSnapshot]:
    rows = manifest_rows(root)
    package_names = {
        project: sorted({name for row_project, _, name in rows if row_project == project}) for project in PROJECTS
    }
    snapshots = {}
    for project in PROJECTS:
        selected = (environment_paths or {}).get(project, root / project / ".venv")
        interpreter = (
            selected / ("Scripts/python.exe" if os.name == "nt" else "bin/python") if selected.is_dir() else selected
        )
        snapshots[project] = probe_environment(interpreter, package_names[project])
    return snapshots


def _report_rows(report: dict) -> dict[tuple[str, str, str], dict]:
    dependencies = report.get("dependencies")
    if not dependencies:
        raise ValueError("report dependency corpus is empty")
    rows = {}
    for row in dependencies:
        key = (row.get("project", ""), row.get("group", ""), normalize_name(row.get("name", "")))
        if key in rows:
            raise ValueError(f"duplicate report dependency row: {'/'.join(key)}")
        rows[key] = row
    return rows


def _require_metadata(report: dict) -> None:
    for field in ("registry_snapshot_date", "python_version", "uv_version"):
        if not report.get(field):
            raise ValueError(f"report metadata is missing: {field}")
    if report.get("projects") != list(PROJECTS):
        raise ValueError(f"report projects must be: {', '.join(PROJECTS)}")
    try:
        registry_date = date.fromisoformat(report["registry_snapshot_date"])
    except ValueError as error:
        raise ValueError("registry snapshot date must be ISO 8601 YYYY-MM-DD") from error
    if registry_date.isoformat() != report["registry_snapshot_date"]:
        raise ValueError("registry snapshot date must be ISO 8601 YYYY-MM-DD")


def current_uv_version() -> str:
    result = subprocess.run(["uv", "--version"], check=True, capture_output=True, text=True)
    return result.stdout.split()[1]


def _vendor_specifier(requirements: list[str], dependency: str) -> str | None:
    for requirement in requirements:
        name, specifier = split_requirement(requirement.split(";", 1)[0].strip())
        if name == dependency:
            return specifier
    return None


def validate_report(*, root: Path, report: dict, snapshots: dict[str, EnvironmentSnapshot]) -> None:
    _require_metadata(report)
    expected = manifest_rows(root)
    locks = lock_versions(root)
    actual = _report_rows(report)
    missing = sorted(set(expected) - set(actual))
    surplus = sorted(set(actual) - set(expected))
    if missing:
        raise ValueError(f"missing dependency row: {'/'.join(missing[0])}")
    if surplus:
        raise ValueError(f"surplus dependency row: {'/'.join(surplus[0])}")

    for project in PROJECTS:
        snapshot = snapshots.get(project)
        if snapshot is None:
            raise ValueError(f"missing environment snapshot: {project}")
        if snapshot.python_version != report["python_version"]:
            raise ValueError(
                f"{project}: recorded Python {report['python_version']} differs from "
                f"environment Python {snapshot.python_version}"
            )
    uv_version = current_uv_version()
    if report["uv_version"] != uv_version:
        raise ValueError(f"recorded uv {report['uv_version']} differs from current uv {uv_version}")

    prefixes = [snapshot.prefix for snapshot in snapshots.values()]
    if len(prefixes) != len(PROJECTS) or len(set(prefixes)) != len(PROJECTS):
        raise ValueError("projects must use distinct environment prefixes")
    for key, requested in expected.items():
        project, _, name = key
        row = actual[key]
        locked = locks[project].get(name)
        if locked is None:
            raise ValueError(f"lock has no exact direct resolution: {project}/{name}")
        if row.get("requested") != requested:
            raise ValueError(f"requested specifier mismatch: {project}/{name}")
        if row.get("resolved") != locked:
            raise ValueError(
                f"report resolution {row.get('resolved')} differs from lock resolution {locked}: {project}/{name}"
            )
        installed = snapshots[project].versions.get(name)
        if installed is None:
            raise ValueError(f"installed package is missing: {project}/{name}")
        if installed != locked:
            raise ValueError(f"{project}/{name}: installed {installed} differs from locked {locked}")
        if row.get("installed") != installed:
            raise ValueError(f"recorded installed version differs from environment: {project}/{name}")
        if not row.get("latest_stable"):
            raise ValueError(f"latest stable version is empty: {project}/{name}")
        held_back = row.get("held_back_by")
        if row["latest_stable"] == locked:
            if held_back:
                raise ValueError(f"holdback recorded for current dependency: {project}/{name}")
            continue
        if not isinstance(held_back, dict):
            raise ValueError(f"held_back_by is required: {project}/{name}")
        for field in ("package", "version", "specifier", "reason"):
            if not held_back.get(field):
                raise ValueError(f"held_back_by.{field} is empty: {project}/{name}")
        vendor = normalize_name(held_back["package"])
        vendor_snapshot = snapshots[project]
        if vendor_snapshot.versions.get(vendor) != held_back["version"]:
            raise ValueError(f"held-back vendor version differs from installed metadata: {project}/{name}")
        vendor_specifier = _vendor_specifier(vendor_snapshot.requirements.get(vendor, []), name)
        if vendor_specifier != held_back["specifier"]:
            raise ValueError(f"vendor metadata requires {name}{vendor_specifier}, not {name}{held_back['specifier']}")


def validate_markdown(root: Path, report: dict) -> None:
    markdown_path = root / "docs/dependency_upgrade.md"
    if not markdown_path.is_file():
        raise ValueError("missing report: docs/dependency_upgrade.md")
    if markdown_path.read_text() != render_markdown(report):
        raise ValueError("rendered documentation mismatch: docs/dependency_upgrade.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--scope", choices=("python", "workspace", "e2e", "all"), required=True)
    parser.add_argument("--environment", action="append", default=[], metavar="PROJECT=PATH")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    report_path = root / "docs/dependency_upgrade.json"
    if not report_path.is_file():
        raise ValueError("missing report: docs/dependency_upgrade.json")
    mappings = {}
    for value in args.environment:
        project, separator, path = value.partition("=")
        if not separator or project not in PROJECTS:
            raise ValueError(f"invalid environment mapping: {value}")
        mappings[project] = Path(path).resolve()
    report = json.loads(report_path.read_text())
    snapshots = probe_scope(root, mappings or None)
    validate_report(root=root, report=report, snapshots=snapshots)
    if args.scope in {"workspace", "all"}:
        validate_workspace_report(root, report, probe_workspace_installed(root, report))
    if args.scope in {"e2e", "all"}:
        validate_e2e_report(root, report, probe_e2e_installed(root, report))
    if args.scope == "all":
        validate_ci_toolchain(root, report)
    validate_markdown(root, report)
    print(f"{args.scope.capitalize()} dependency upgrade report is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
