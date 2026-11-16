#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PRIMARY="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
RUNNER="$PRIMARY/scripts/super-test.sh"
[ -f "$RUNNER" ] || { echo "ERROR: durable runner missing: $RUNNER" >&2; exit 1; }
LABEL=com.divineruin.super-test
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/.xp/super/flake-artifacts"
mkdir -p "$(dirname "$PLIST")" "$LOGS"
TOOL_PATH=
for tool in bun uv docker node python3 git; do
  location="$(command -v "$tool")" || { echo "ERROR: missing $tool" >&2; exit 1; }
  TOOL_PATH="${TOOL_PATH:+$TOOL_PATH:}$(dirname "$location")"
done
TOOL_PATH="$TOOL_PATH:/usr/bin:/bin:/usr/sbin:/sbin"
python3 - "$PLIST" "$LABEL" "$RUNNER" "$PRIMARY" "$LOGS" "$TOOL_PATH" <<'PY'
import plistlib
import sys

path, label, runner, primary, logs, tool_path = sys.argv[1:]
with open(path, "wb") as output:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": ["/bin/bash", runner],
        "WorkingDirectory": primary,
        "EnvironmentVariables": {"PATH": tool_path},
        "StartCalendarInterval": [
            {"Weekday": day, "Hour": 2, "Minute": 0} for day in (2, 4, 6)
        ],
        "StandardOutPath": logs + "/launchd.stdout.log",
        "StandardErrorPath": logs + "/launchd.stderr.log",
    }, output)
PY
plutil -lint "$PLIST"
DOMAIN="gui/$(id -u)"
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL"
fi
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl print "$DOMAIN/$LABEL" >/dev/null
echo "Installed $LABEL: $PLIST; Tuesday, Thursday, Saturday at 02:00"
