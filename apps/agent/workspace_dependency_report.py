import glob
import json
import re
import subprocess
import tomllib
from pathlib import Path

GROUPS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def _jsonc(path: Path) -> dict:
    text = re.sub(r",\s*([}\]])", r"\1", path.read_text())
    return json.loads(text)


def workspace_manifests(root: Path) -> dict[str, dict]:
    root_manifest = root / "package.json"
    if not root_manifest.is_file():
        raise ValueError("missing manifest: package.json")
    manifest = json.loads(root_manifest.read_text())
    projects = {".": manifest}
    matched = set()
    for pattern in manifest.get("workspaces", []):
        for candidate in glob.glob(str(root / pattern / "package.json")):
            path = Path(candidate)
            project = path.parent.relative_to(root).as_posix()
            projects[project] = json.loads(path.read_text())
            matched.add(project)
    if not matched:
        raise ValueError("workspace manifest corpus is empty")
    return dict(sorted(projects.items()))


def manifest_rows(root: Path) -> dict[tuple[str, str, str], str]:
    rows = {}
    for project, manifest in workspace_manifests(root).items():
        for group in GROUPS:
            for name, requested in manifest.get(group, {}).items():
                key = (project, group, name)
                if key in rows:
                    raise ValueError(f"duplicate workspace dependency: {'/'.join(key)}")
                rows[key] = requested
    if not rows:
        raise ValueError("workspace dependency corpus is empty")
    return rows


def _resolution(name: str, package: list) -> str:
    source = package[0]
    prefix = f"{name}@"
    if not source.startswith(prefix):
        raise ValueError(f"invalid lock resolution for {name}: {source}")
    return source[len(prefix) :]


def lock_rows(root: Path) -> dict[tuple[str, str, str], str]:
    path = root / "bun.lock"
    if not path.is_file():
        raise ValueError("missing lock: bun.lock")
    lock = _jsonc(path)
    manifests = workspace_manifests(root)
    importers = lock.get("workspaces", {})
    packages = lock.get("packages", {})
    rows = {}
    for key, requested in manifest_rows(root).items():
        project, group, name = key
        importer = "" if project == "." else project
        locked_requested = importers.get(importer, {}).get(group, {}).get(name)
        if locked_requested != requested:
            raise ValueError(f"lock request differs from manifest: {project}/{group}/{name}")
        workspace_name = manifests[project].get("name", "")
        nested_key = f"{workspace_name}/{name}"
        package = packages.get(nested_key) if project != "." else None
        package = package or packages.get(name)
        if not package:
            raise ValueError(f"lock has no direct resolution: {project}/{name}")
        rows[key] = _resolution(name, package)
    return rows


def _installed_path(root: Path, project: str, name: str) -> Path:
    relative = Path("node_modules") / name
    candidates = [root / relative] if project == "." else [root / project / relative, root / relative]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ValueError(f"installed package is missing: {project}/{name}")


def probe_installed(root: Path, report: dict) -> dict[tuple[str, str], str]:
    installed = {}
    for row in report.get("workspace_dependencies", []):
        key = (row["project"], row["name"])
        if key in installed:
            continue
        path = _installed_path(root, *key)
        locked = row["locked"]
        if locked.startswith("workspace:"):
            expected = (root / locked.removeprefix("workspace:")).resolve()
            if path.resolve() != expected:
                raise ValueError(f"installed source differs from lock: {'/'.join(key)}")
            value = locked
        elif locked.startswith(("github:", "git+")):
            commit = locked.rsplit("#", 1)[-1]
            if commit not in str(path.resolve()):
                raise ValueError(f"installed source differs from lock: {'/'.join(key)}")
            value = locked
        else:
            value = json.loads((path / "package.json").read_text())["version"]
        installed[key] = value
    return installed


def validate_workspace_report(root: Path, report: dict, installed: dict[tuple[str, str], str]) -> None:
    for field in ("bun_version", "minimum_release_age"):
        if report.get(field) is None:
            raise ValueError(f"workspace report metadata is missing: {field}")
    bunfig_path = root / "bunfig.toml"
    if not bunfig_path.is_file():
        raise ValueError("missing policy: bunfig.toml")
    policy = tomllib.loads(bunfig_path.read_text()).get("install", {}).get("minimumReleaseAge")
    if report["minimum_release_age"] != policy:
        raise ValueError("minimum_release_age differs from bunfig.toml policy")
    running_bun = subprocess.run(["bun", "--version"], check=True, capture_output=True, text=True).stdout.strip()
    if report["bun_version"] != running_bun:
        raise ValueError(f"recorded Bun {report['bun_version']} differs from running Bun {running_bun}")
    expected = manifest_rows(root)
    locks = lock_rows(root)
    projects = list(workspace_manifests(root))
    recorded_projects = report.get("workspace_projects", [])
    missing_projects = sorted(set(projects) - set(recorded_projects))
    surplus_projects = sorted(set(recorded_projects) - set(projects))
    if missing_projects:
        raise ValueError(f"missing workspace project: {missing_projects[0]}")
    if surplus_projects:
        raise ValueError(f"surplus workspace project: {surplus_projects[0]}")
    root_overrides = workspace_manifests(root)["."].get("overrides", {})
    reported_overrides = {row.get("name"): row.get("requested") for row in report.get("overrides", [])}
    if reported_overrides != root_overrides:
        raise ValueError("root override inventory differs from package.json")

    actual = {}
    for row in report.get("workspace_dependencies", []):
        key = (row.get("project", ""), row.get("group", ""), row.get("name", ""))
        if key in actual:
            raise ValueError(f"duplicate workspace dependency row: {'/'.join(key)}")
        actual[key] = row
    if not actual:
        raise ValueError("workspace report dependency corpus is empty")
    missing = sorted(set(expected) - set(actual))
    surplus = sorted(set(actual) - set(expected))
    if missing:
        raise ValueError(f"missing workspace dependency row: {'/'.join(missing[0])}")
    if surplus:
        raise ValueError(f"surplus workspace dependency row: {'/'.join(surplus[0])}")

    for key, requested in expected.items():
        project, _, name = key
        row = actual[key]
        if row.get("requested") != requested:
            raise ValueError(f"requested range differs from manifest: {project}/{name}")
        if row.get("locked") != locks[key]:
            raise ValueError(f"lock resolution differs from report: {project}/{name}")
        observed = installed.get((project, name))
        if observed != row.get("installed") or observed != locks[key]:
            raise ValueError(f"installed resolution differs from lock: {project}/{name}")
        for field in ("candidate", "registry_latest"):
            if not row.get(field):
                raise ValueError(f"{field} is empty: {project}/{name}")
        if row["candidate"] != row["registry_latest"] and not row.get("reason"):
            raise ValueError(f"candidate difference requires reason: {project}/{name}")
        if project == "apps/mobile" and row.get("held_by") != "story 207/208":
            raise ValueError(f"apps/mobile dependency must be held by story 207/208: {name}")
        if (
            project == "apps/web"
            and name in {"react", "react-dom", "@types/react", "@types/react-dom"}
            and row.get("held_by") != "story 207/208"
        ):
            raise ValueError(f"apps/web React dependency must be held by story 207/208: {name}")
    if "story 210" not in report.get("exclusions", {}).get("e2e", ""):
        raise ValueError("e2e exclusion must name story 210")
