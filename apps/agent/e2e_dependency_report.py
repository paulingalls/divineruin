import json
import re
from pathlib import Path

GROUPS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def _jsonc(path: Path) -> dict:
    return json.loads(re.sub(r",\s*([}\]])", r"\1", path.read_text()))


def manifest_rows(root: Path) -> dict[tuple[str, str], str]:
    path = root / "e2e/package.json"
    if not path.is_file():
        raise ValueError("missing manifest: e2e/package.json")
    manifest = json.loads(path.read_text())
    rows = {(group, name): requested for group in GROUPS for name, requested in manifest.get(group, {}).items()}
    if not rows:
        raise ValueError("e2e manifest dependency corpus is empty")
    return rows


def lock_rows(root: Path) -> dict[tuple[str, str], str]:
    path = root / "e2e/bun.lock"
    if not path.is_file():
        raise ValueError("missing lock: e2e/bun.lock")
    lock = _jsonc(path)
    importer = lock.get("workspaces", {}).get("")
    if not importer:
        raise ValueError("e2e lock importer is missing")
    packages = lock.get("packages", {})
    rows = {}
    for key, requested in manifest_rows(root).items():
        group, name = key
        if importer.get(group, {}).get(name) != requested:
            raise ValueError(f"e2e lock request differs from manifest: {group}/{name}")
        package = packages.get(name)
        if not package or not package[0].startswith(f"{name}@"):
            raise ValueError(f"e2e lock has no exact direct resolution: {name}")
        rows[key] = package[0].removeprefix(f"{name}@")
    return rows


def probe_installed(root: Path, report: dict) -> dict[str, str]:
    installed = {}
    for row in report.get("e2e_dependencies", []):
        name = row["name"]
        path = root / "e2e/node_modules" / name / "package.json"
        if not path.is_file():
            raise ValueError(f"installed e2e package is missing: {name}")
        installed[name] = json.loads(path.read_text())["version"]
    return installed


def validate_e2e_report(root: Path, report: dict, installed: dict[str, str]) -> None:
    expected = manifest_rows(root)
    locked = lock_rows(root)
    actual = {}
    for row in report.get("e2e_dependencies", []):
        key = (row.get("group", ""), row.get("name", ""))
        if key in actual:
            raise ValueError(f"duplicate e2e dependency row: {'/'.join(key)}")
        actual[key] = row
    if not actual:
        raise ValueError("e2e report dependency corpus is empty")
    missing = sorted(set(expected) - set(actual))
    surplus = sorted(set(actual) - set(expected))
    if missing:
        raise ValueError(f"missing e2e dependency row: {'/'.join(missing[0])}")
    if surplus:
        raise ValueError(f"surplus e2e dependency row: {'/'.join(surplus[0])}")
    for key, requested in expected.items():
        _, name = key
        row = actual[key]
        if row.get("requested") != requested:
            raise ValueError(f"e2e requested range differs from manifest: {name}")
        if row.get("locked") != locked[key]:
            raise ValueError(f"e2e locked resolution differs from lock: {name}")
        if row.get("installed") != installed.get(name) or installed.get(name) != locked[key]:
            raise ValueError(f"e2e installed resolution differs from lock: {name}")
        for field in ("candidate", "registry_latest"):
            if not row.get(field):
                raise ValueError(f"e2e {field} is empty: {name}")
        if row["candidate"] != row["registry_latest"] and not row.get("reason"):
            raise ValueError(f"e2e candidate difference requires reason: {name}")
    if "e2e" in report.get("exclusions", {}):
        raise ValueError("stale e2e exclusion remains in the report")

    exceptions = report.get("e2e_release_age_exceptions")
    if not isinstance(exceptions, list):
        raise ValueError("e2e release-age exceptions are missing")
    versions = {row["name"]: row["locked"] for row in actual.values()}
    for exception in exceptions:
        name = exception.get("name", "")
        if versions.get(name) != exception.get("version"):
            raise ValueError(f"e2e release-age exception differs from lock: {name}")
        for field in ("published_at", "command", "evidence"):
            if not exception.get(field):
                raise ValueError(f"e2e release-age exception {field} is empty: {name}")
