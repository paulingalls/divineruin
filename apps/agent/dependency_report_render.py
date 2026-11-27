def render_markdown(report: dict) -> str:
    check = report.get("report_check")
    execution = (
        f"`--check --scope all` exited {check['exit_status']} at `{check['commit']}` on {check['checked_at']}."
        if check
        else "All-scope check execution has yet to be recorded."
    )
    lines = [
        "# Dependency upgrade",
        "",
        f"Registry snapshot: {report['registry_snapshot_date']} (acquisition completed {report['registry_acquired_at']})",
        "",
        f"Toolchain: CPython {report['python_version']}, uv {report['uv_version']}, Bun {report.get('bun_version', 'unreported')}",
        "",
        f"Execution evidence: {execution}",
        "",
        "## Python environments",
        "",
    ]
    for project in report["projects"]:
        lines.extend(
            [
                f"### {project}",
                "",
                "| Group | Dependency | Requested | Resolved / installed | Latest stable | Holdback |",
                "|---|---|---|---|---|---|",
            ]
        )
        for row in (item for item in report["dependencies"] if item["project"] == project):
            held = row.get("held_back_by")
            holdback = held["reason"] if held else "—"
            lines.append(
                f"| {row['group']} | {row['name']} | `{row['requested']}` | {row['resolved']} / {row['installed']} | {row['latest_stable']} | {holdback} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Bun workspace",
            "",
            f"Release age policy: {report['minimum_release_age']} seconds.",
            "",
            "Candidate is the version selected in the committed graph. Registry columns show — for Git and workspace sources.",
            "",
            "| Project | Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["workspace_dependencies"]:
        decision = row.get("reason") or "Current"
        if row.get("held_by"):
            decision = f"Held by {row['held_by']}: {decision}"
        lines.append(
            f"| {row['project']} | {row['group']} | {row['name']} | `{row['requested']}` | {row['locked']} / {row['installed']} | {row['candidate']} | {row['registry_latest']} | {decision} |"
        )
    lines.extend(
        [
            "",
            "## Independent browser toolchain",
            "",
            "| Group | Dependency | Requested | Locked / installed | Candidate | Registry latest | Decision |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["e2e_dependencies"]:
        lines.append(
            f"| {row['group']} | {row['name']} | `{row['requested']}` | {row['locked']} / {row['installed']} | {row['candidate']} | {row['registry_latest']} | {row.get('reason') or 'Current'} |"
        )
    if report["e2e_release_age_exceptions"]:
        lines.extend(["", "| Release-age exception | Published | Command | Evidence |", "|---|---|---|---|"])
    for exception in report["e2e_release_age_exceptions"]:
        lines.append(
            f"| {exception['name']}@{exception['version']} | {exception['published_at']} | `{exception['command']}` | {exception['evidence']} |"
        )
    mobile = report["mobile_baseline"]
    minimums = mobile["platform_minimums"]
    lines.extend(
        [
            "",
            "## Mobile SDK 58 baseline",
            "",
            f"- Expo {mobile['expo']}, React Native {mobile['react_native']}, {mobile['engine']}.",
            f"- Android {minimums['android']} (compile SDK {minimums['compile_sdk']}, target SDK {minimums['target_sdk']}), iOS {minimums['ios']}, Xcode {minimums['xcode']}.",
            f"- Config plugins: {', '.join(mobile['plugins'])}.",
            f"- Patch files: {', '.join(mobile['patches']) if mobile['patches'] else 'none'}.",
            "",
            "| Git dependency | Requested | Locked commit |",
            "|---|---|---|",
        ]
    )
    for source in mobile["git_sources"]:
        lines.append(f"| {source['name']} | `{source['requested']}` | `{source['commit']}` |")
    compatibility = mobile["compatibility_exceptions"]
    lines.extend(["", "Compatibility exceptions:"])
    if not compatibility:
        lines.append("- none")
    for exception in compatibility:
        lines.append(
            f"- {exception['producer']} declares `{exception['declared_peer']}`; selected `{exception['selected']}`. {exception['evidence']}"
        )
    exemption = report["mobile_release_age_exemption"]
    lines.extend(
        [
            "",
            f"### One-off Expo release-age exemption, {exemption['date']}",
            "",
            f"{exemption['evidence']} [Expo 58.1.0 upgrade]({exemption['reference']})",
            "",
            "| Package | Previous | Exempted version |",
            "|---|---|---|",
        ]
    )
    for package in exemption["packages"]:
        lines.append(f"| {package['name']} | {package['previous']} | {package['version']} |")

    overrides = report.get("overrides", [])
    if overrides:
        lines.extend(
            [
                "",
                "## Root resolution overrides",
                "",
                "| Override | Requested | Reason |",
                "|---|---|---|",
            ]
        )
        for row in overrides:
            lines.append(f"| {row['name']} | `{row['requested']}` | {row['reason']} |")
    lines.extend(["", "## Infrastructure holds", ""])
    for hold in report["infrastructure_holds"]:
        lines.append(f"- `{hold['reference']}` ({hold['name']}): {hold['status']}. {hold['reason']}")

    record = report["evidence_record"]
    lines.extend(
        [
            "",
            "## Historical validation outcomes",
            "",
            f"The SDK 57 validation record was accepted at `{record['accepted_commit']}` on {record['accepted_at']}.",
            "",
            "### Native builds",
        ]
    )
    ios = mobile["native_validation"]["ios"]
    android = mobile["native_validation"]["android"]
    lines.extend(
        [
            "",
            "| Platform | Prebuild | Build | Device/install | Acceptance |",
            "|---|---|---|---|---|",
            f"| iOS | {ios['prebuild']} | {ios['build']} | {ios['install']} on {ios['runtime']} (`{ios['simulator_udid']}`) | launch: {ios['launch_flow']}; auth: {ios['auth_flow']} |",
            f"| Android | {android['prebuild']} | {android['build']} | {android['device']} | export: {android['export']} |",
        ]
    )
    transport = mobile["native_transport"]
    lines.extend(
        [
            "",
            "### Native LiveKit transport",
            "",
            f"- Status: {transport['status']} on `{transport['simulator_udid']}` with {transport['sdk']}.",
            f"- Python to iOS audio: {transport['received_audio']}.",
            f"- iOS microphone to Python: {transport['microphone_audio']}.",
            f"- Game event and HUD: {transport['game_events_hud']}.",
            f"- Fault guards: {', '.join(transport['fault_guards'])}.",
            f"- Evidence: {transport['artifact']}; driver: {transport['tool']}; Expo MCP: {transport['expo_mcp']}.",
        ]
    )
    if report.get("validation_outcomes"):
        lines.extend(["", "### Other recorded checks", "", "| Lane | Recorded outcome | Evidence |", "|---|---|---|"])
        for outcome in report["validation_outcomes"]:
            lines.append(f"| {outcome['lane']} | {outcome['status']} | {outcome['evidence']} |")
    lines.extend(
        [
            "",
            "The committed agent/scripts `uv.lock` files and root/e2e `bun.lock` files are the exact transitive dependency records.",
            "",
        ]
    )
    return "\n".join(lines)
