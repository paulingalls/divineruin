#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REMOTE="$(git remote get-url origin)"
# A copy outside every checkout: a branch switch in the primary cannot remove or change the scheduled runner.
# Rerun this installer to update it.
RUNNER="$HOME/.xp/super/super-test.sh"
LABEL=com.divineruin.super-test
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/.xp/super/flake-artifacts"
mkdir -p "$(dirname "$PLIST")" "$LOGS"
TOOL_PATH=
for tool in bun uv docker node python3 git gh gitleaks; do
  location="$(command -v "$tool")" || { echo "ERROR: missing $tool" >&2; exit 1; }
  TOOL_PATH="${TOOL_PATH:+$TOOL_PATH:}$(dirname "$location")"
done
TOOL_PATH="$TOOL_PATH:/usr/bin:/bin:/usr/sbin:/sbin"
env -u GH_TOKEN -u GITHUB_TOKEN -u GH_ENTERPRISE_TOKEN -u GITHUB_ENTERPRISE_TOKEN gh auth status
mkdir -p "$(dirname "$RUNNER")"
cp scripts/super-test.sh "$RUNNER"
# The dedicated clone keeps the host session's repository untouched.
python3 - "$PLIST" "$LABEL" "$RUNNER" "$REMOTE" "$HOME/.xp/super" "$LOGS" "$TOOL_PATH" <<'PY'
import plistlib
import sys

path, label, runner, remote, working_dir, logs, tool_path = sys.argv[1:]
with open(path, "wb") as output:
    plistlib.dump({
        "Label": label,
        "ProgramArguments": ["/bin/bash", runner],
        "WorkingDirectory": working_dir,
        "EnvironmentVariables": {"PATH": tool_path, "SUPER_REMOTE": remote},
        "StartCalendarInterval": {"Hour": 0, "Minute": 30},
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
echo "Installed $LABEL: $PLIST; nightly at 00:30"
