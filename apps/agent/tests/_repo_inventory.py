"""Freeze the judged sandbox tree before tests create transient source files."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXCLUDED = {".venv", "__pycache__", ".pytest_cache", "node_modules"}


def snapshot_repository():
    if os.environ.get("PROOF_AGENT_PROVIDER") != "dev" or os.environ.get("PYTEST_XDIST_WORKER"):
        return
    paths = []
    for directory in ("apps", "packages", "scripts", "e2e", "docs"):
        for base, dirs, files in os.walk(ROOT / directory, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
            paths.extend(str((Path(base) / f).relative_to(ROOT)) for f in sorted(files))
    required = {
        "apps/agent/agent.py",
        "scripts/seed_content.py",
        "packages/shared/package.json",
        "e2e/package.json",
        "docs/INDEX.md",
    }
    if not required <= set(paths):
        raise RuntimeError(f"incomplete proof inventory: {sorted(required - set(paths))}")
    target = ROOT / ".proof-inventory.json"
    target.write_text(json.dumps(sorted(paths)))
    os.environ["PROOF_REPO_INVENTORY"] = str(target)


def repository_files(root, *patterns, untracked=False):
    if os.environ.get("PROOF_AGENT_PROVIDER"):
        paths = json.loads(Path(os.environ["PROOF_REPO_INVENTORY"]).read_text())
        prefix = root.relative_to(ROOT)
        relative = [Path(p).relative_to(prefix) for p in paths if Path(p).is_relative_to(prefix)]
        return [p for p in relative if any(p.match(pattern) or p.parts[0] == pattern for pattern in patterns)]
    args = ["git", "ls-files", "-z"]
    if untracked:
        args += ["--cached", "--others", "--exclude-standard"]
    result = subprocess.run([*args, "--", *patterns], cwd=root, check=True, capture_output=True, text=True)
    return [Path(p) for p in result.stdout.split("\0") if p]
