def render_markdown(report: dict) -> str:
    lines = [
        "# Dependency upgrade",
        "",
        f"Registry snapshot: {report['registry_snapshot_date']}  ",
        f"Toolchain: CPython {report['python_version']}; uv {report['uv_version']}; Bun {report.get('bun_version', 'unreported')}",
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
            holdback = (
                "—"
                if not held
                else f"{held['package']}=={held['version']} requires {row['name']}{held['specifier']}: {held['reason']}"
            )
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
    overrides = report.get("overrides", [])
    if overrides:
        lines.extend(
            [
                "",
                "### Root resolution overrides",
                "",
                "| Override | Requested | Reason |",
                "|---|---|---|",
            ]
        )
        for row in overrides:
            lines.append(f"| {row['name']} | `{row['requested']}` | {row['reason']} |")
    lines.extend(
        [
            "",
            f"E2E exclusion: {report['exclusions']['e2e']}",
            "",
            "The committed `uv.lock` and root `bun.lock` files are the exact transitive dependency records.",
            "",
        ]
    )
    return "\n".join(lines)
