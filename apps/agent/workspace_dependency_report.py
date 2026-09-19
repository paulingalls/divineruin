import glob
import json
import re
import subprocess
import tomllib
from pathlib import Path

from native_transport.evidence import reject_credentials

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
            bun_tag = path / ".bun-tag"
            installed_source = bun_tag.read_text().strip() if bun_tag.is_file() else str(path.resolve())
            if commit not in installed_source:
                raise ValueError(f"installed source differs from lock: {'/'.join(key)}")
            value = locked
        else:
            value = json.loads((path / "package.json").read_text())["version"]
        installed[key] = value
    return installed


def _configured_plugins(root: Path) -> list[str]:
    path = root / "apps/mobile/app.json"
    if not path.is_file():
        raise ValueError("missing mobile config: apps/mobile/app.json")
    plugins = json.loads(path.read_text()).get("expo", {}).get("plugins", [])
    return [plugin[0] if isinstance(plugin, list) else plugin for plugin in plugins]


# Vendored trees ship their own .patch files (uv wheels under .venv, Expo caches
# under .expo), and none of them is a mobile patch this baseline claims to inventory.
_UNWALKED = {".git", "node_modules", ".venv", ".expo"}


def _patch_inventory(root: Path) -> list[str]:
    files = [
        path for path in root.rglob("*") if path.is_file() and not _UNWALKED.intersection(path.relative_to(root).parts)
    ]
    if not files:
        raise ValueError("repository file corpus is empty while checking patches")
    return sorted(path.relative_to(root).as_posix() for path in files if path.suffix == ".patch")


def _validate_mobile_baseline(root: Path, report: dict, rows: dict[tuple[str, str, str], dict]) -> None:
    baseline = report.get("mobile_baseline")
    if not isinstance(baseline, dict):
        raise ValueError("mobile baseline is missing")
    if report.get("schema_version") != 3:
        raise ValueError("complete dependency inventory requires schema_version 3")

    mobile = {name: row for (project, _, name), row in rows.items() if project == "apps/mobile"}
    for field, package in (("expo", "expo"), ("react_native", "react-native")):
        if baseline.get(field) != mobile.get(package, {}).get("locked"):
            raise ValueError(f"mobile baseline {field} differs from lock")
    if baseline.get("engine") != "Hermes V1 (SDK 57 default)":
        raise ValueError("mobile baseline engine must be the SDK 57 Hermes V1 default")
    expected_minimums = {
        "android": "7+",
        "compile_sdk": 36,
        "target_sdk": 36,
        "ios": "16.4+",
        "xcode": "26.4+",
    }
    if baseline.get("platform_minimums") != expected_minimums:
        raise ValueError("mobile baseline platform minimums differ from SDK 57")
    if baseline.get("plugins") != _configured_plugins(root):
        raise ValueError("mobile baseline plugin inventory differs from app.json")

    git_sources = baseline.get("git_sources")
    expected_git = []
    for name, row in mobile.items():
        if row["requested"].startswith(("github:", "git+")):
            expected_git.append(
                {
                    "name": name,
                    "requested": row["requested"],
                    "locked": row["locked"],
                    "commit": row["locked"].rsplit("#", 1)[-1],
                }
            )
    if git_sources != expected_git:
        raise ValueError("mobile baseline git source inventory differs from manifest and lock")
    if baseline.get("patches") != _patch_inventory(root):
        raise ValueError("mobile baseline patch inventory differs from repository")

    expected_livekit = {
        "@livekit/react-native": "2.12.0",
        "@livekit/react-native-webrtc": "144.1.2",
    }
    for name, expected in expected_livekit.items():
        if mobile.get(name, {}).get("locked") != expected:
            raise ValueError(f"mobile baseline incompatible LiveKit graph: {name}")

    exceptions = baseline.get("release_age_exceptions")
    if not isinstance(exceptions, list) or {row.get("name") for row in exceptions} != {
        "expo",
        "expo-asset",
        "expo-notifications",
        "expo-router",
    }:
        raise ValueError("mobile baseline release-age exceptions are incomplete")
    for exception in exceptions:
        name = exception["name"]
        if exception.get("version") != mobile.get(name, {}).get("locked"):
            raise ValueError(f"release-age exception differs from lock: {name}")
        for field in ("published_at", "command", "evidence"):
            if not exception.get(field):
                raise ValueError(f"release-age exception {field} is empty: {name}")

    compatibility = baseline.get("compatibility_exceptions")
    if not isinstance(compatibility, list):
        raise ValueError("mobile baseline compatibility exceptions are missing")
    for exception in compatibility:
        for field in ("producer", "declared_peer", "selected", "evidence"):
            if not exception.get(field):
                raise ValueError(f"compatibility exception {field} is empty")
    if compatibility:
        raise ValueError("mobile baseline compatibility exceptions must be empty for the in-range graph")

    native = baseline.get("native_validation", {})
    ios = native.get("ios", {})
    for field in ("prebuild", "build", "install", "launch_flow", "auth_flow"):
        if ios.get(field) != "passed":
            raise ValueError(f"iOS native validation is not passed: {field}")
    if not ios.get("simulator_udid") or not ios.get("runtime"):
        raise ValueError("iOS native validation device evidence is empty")

    transport = baseline.get("native_transport", {})
    if transport.get("status") != "passed":
        raise ValueError("native transport status must be passed")
    if transport.get("simulator_udid") != ios.get("simulator_udid"):
        raise ValueError("native transport simulator differs from iOS validation")
    if transport.get("tool") != "maestro":
        raise ValueError("native transport tool must be maestro")
    if transport.get("expo_mcp") != "unavailable_in_tool_catalog":
        raise ValueError("Expo MCP capability must be unavailable_in_tool_catalog")
    for field in ("sdk", "received_audio", "microphone_audio", "game_events_hud", "artifact"):
        if not transport.get(field):
            raise ValueError(f"native transport evidence is empty: {field}")
    if transport.get("fault_guards") != ["received-audio", "session-init-hud"]:
        raise ValueError("native transport fault guards are incomplete")

    reject_credentials(transport)
    android = native.get("android", {})
    for field in ("prebuild", "export"):
        if android.get(field) != "passed":
            raise ValueError(f"Android validation is not passed: {field}")
    for field in ("build", "device"):
        value = android.get(field, "")
        if value != "passed" and not value.startswith("missing:"):
            raise ValueError(f"Android validation must report passed or missing: {field}")


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
        if project == "apps/mobile" and row["candidate"] != row["registry_latest"] and not row.get("held_by"):
            raise ValueError(f"mobile hold requires producer: {name}")
        if (
            project == "apps/web"
            and name in {"react", "react-dom", "@types/react", "@types/react-dom"}
            and row["candidate"] != row["registry_latest"]
            and not row.get("held_by")
        ):
            raise ValueError(f"apps/web React hold requires producer: {name}")
    _validate_mobile_baseline(root, report, actual)
