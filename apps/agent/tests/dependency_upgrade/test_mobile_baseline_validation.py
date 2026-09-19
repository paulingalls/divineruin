from copy import deepcopy

import pytest
from test_workspace_report_validation import _copy_scope, _report, _validate

from workspace_dependency_report import _validate_mobile_baseline


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("expo",), "0.0.0", "expo differs from lock"),
        (("react_native",), "0.0.0", "react_native differs from lock"),
        (("engine",), "legacy Hermes", "Hermes V1 default"),
        (("platform_minimums", "ios"), "15+", "platform minimums"),
        (("plugins",), [], "plugin inventory"),
        (("git_sources",), [], "git source inventory"),
        (("release_age_exceptions",), [], "release-age exceptions"),
        (("native_validation", "ios", "auth_flow"), "missing", "iOS native validation"),
        (("native_validation", "android", "prebuild"), "missing", "Android validation"),
    ],
)
def test_mobile_baseline_faults_fail(tmp_path, path, value, message):
    root = _copy_scope(tmp_path)
    report = _report(root)
    target = report["mobile_baseline"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        _validate(root, report)


def test_release_exception_version_and_android_missing_floor_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    report["mobile_baseline"]["release_age_exceptions"][0]["version"] = "0.0.0"
    with pytest.raises(ValueError, match="exception differs from lock"):
        _validate(root, report)

    report = deepcopy(_report(root))
    report["mobile_baseline"]["native_validation"]["android"]["device"] = "unknown"
    with pytest.raises(ValueError, match="passed or missing"):
        _validate(root, report)


def test_livekit_graph_and_metadata_exception_faults_fail(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    _validate(root, report)

    report["mobile_baseline"]["compatibility_exceptions"] = [{"producer": "plugin"}]
    with pytest.raises(ValueError, match="compatibility exception declared_peer"):
        _validate(root, report)

    report = _report(root)
    report["mobile_baseline"]["compatibility_exceptions"] = [
        {
            "producer": "plugin",
            "declared_peer": "dependency@^2",
            "selected": "dependency@3",
            "evidence": "bypassed vendor bounds",
        }
    ]
    with pytest.raises(ValueError, match="must be empty"):
        _validate(root, report)


@pytest.mark.parametrize(
    ("name", "version"),
    [("@livekit/react-native", "3.0.0"), ("@livekit/react-native-webrtc", "144.2.0")],
)
def test_incompatible_livekit_graph_fails(name, version, tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    rows = {(row["project"], row["group"], row["name"]): row for row in report["workspace_dependencies"]}
    rows[("apps/mobile", "dependencies", name)]["locked"] = version
    with pytest.raises(ValueError, match="incompatible LiveKit graph"):
        _validate_mobile_baseline(root, report, rows)


def test_patch_inventory_walks_our_sources_and_skips_vendored_trees(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)

    for vendored in ("node_modules/pkg", "apps/agent/.venv/lib/pkg", "apps/mobile/.expo"):
        path = root / vendored / "vendor.patch"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("--- vendored\n")
    _validate(root, report)

    ours = root / "apps/mobile/patches/react-native+0.86.3.patch"
    ours.parent.mkdir(parents=True, exist_ok=True)
    ours.write_text("--- ours\n")
    with pytest.raises(ValueError, match="patch inventory"):
        _validate(root, report)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("status",), "missing", "native transport status"),
        (("simulator_udid",), "wrong", "native transport simulator"),
        (("tool",), "skipped", "native transport tool"),
        (("expo_mcp",), "connected", "Expo MCP capability"),
        (("received_audio",), "", "native transport evidence"),
        (("microphone_audio",), "", "native transport evidence"),
        (("game_events_hud",), "", "native transport evidence"),
        (("artifact",), "", "native transport evidence"),
        (("fault_guards",), [], "fault guards"),
    ],
)
def test_native_transport_evidence_faults_fail(tmp_path, path, value, message):
    root = _copy_scope(tmp_path)
    report = _report(root)
    target = report["mobile_baseline"]["native_transport"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        _validate(root, report)


def test_native_transport_rejects_credential_fields_and_empty_block(tmp_path):
    root = _copy_scope(tmp_path)
    report = _report(root)
    report["mobile_baseline"]["native_transport"] = {}
    with pytest.raises(ValueError, match="native transport status"):
        _validate(root, report)

    report = _report(root)
    report["mobile_baseline"]["native_transport"]["nested"] = {"token": "leak"}
    with pytest.raises(ValueError, match="credential field"):
        _validate(root, report)
