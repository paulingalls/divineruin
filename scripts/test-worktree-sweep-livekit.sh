#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
unset DATABASE_URL REDIS_URL
python3 - "$@" <<'PY'
import json, os, pathlib, shutil, subprocess, sys, tempfile

root = pathlib.Path(os.environ["ROOT"])
STUB = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

p = Path(os.environ["STATE"])
d = json.loads(p.read_text())
a = sys.argv[1:]


def save():
    p.write_text(json.dumps(d))


def out(rows):
    print("\n".join(rows))


if a[:2] == ["compose", "ls"]:
    if d.get("fail") == "compose":
        sys.exit(1)
    print(d.get("listing", json.dumps([{"Name": x} for x in d["projects"]])))
    sys.exit()
if a[0] in ("ps", "volume", "network"):
    filters = [
        (a[i + 1][6:] if a[i + 1].startswith("label=") else a[i + 1])
        for i, x in enumerate(a)
        if x == "--filter"
    ]
    kind = {"ps": "container", "volume": "volume", "network": "network"}[a[0]]
    if d.get("fail") == kind or (d.get("fail") == "resource-" + kind and "com.docker.compose.project=stale" in filters):
        sys.exit(1)
    if (
        d.get("fail") == "existence"
        and d.get("down")
        and any(x.startswith("id=") for x in a)
    ):
        sys.exit(1)
    rows = []
    for id, r in d["resources"].items():
        if r["kind"] != kind:
            continue
        if all(
            (
                id.startswith(f[3:])
                if f.startswith("id=")
                else r["labels"].get(f.split("=", 1)[0]) == f.split("=", 1)[1]
            )
            for f in filters
        ):
            rows.append(id)
    out(rows)
    sys.exit()
if a[0] == "inspect":
    id = a[-1]
    r = d["resources"].get(id)
    if not r or r.get("unreadable"):
        sys.exit(1)
    r["reads"] = r.get("reads", 0) + 1
    save()
    labels = r["labels"].copy()
    if r.get("change") and r["reads"] > 1:
        labels["com.divineruin.clone"] = "changed"
    print(r.get("raw", json.dumps(labels)))
    sys.exit()
if a[0] == "compose" and a[-2:] == ["down", "-v"]:
    project = a[a.index("-p") + 1]
    d["mutations"].append("down " + project)
    d["down"] = True
    if d.get("fail") == "down":
        save()
        sys.exit(1)
    d["resources"] = {
        i: r
        for i, r in d["resources"].items()
        if r["labels"].get("com.docker.compose.project") != project or r.get("orphan")
    }
    save()
    sys.exit()
if a[:2] == ["rm", "-f"]:
    d["mutations"].append("rm " + a[-1])
    save()
    if d.get("fail") == "rm" or a[-1] not in d["resources"]:
        sys.exit(1)
    del d["resources"][a[-1]]
    save()
    sys.exit()
sys.exit("unexpected Docker command " + str(a))
"""
cases = [
    "mixed",
    "multiple",
    "livekit-only",
    "compose-only",
    "owned-live-only",
    "both-empty",
    "foreign-only",
    "compose-failure",
    "container-failure",
    "invalid-compose-json",
    "invalid-compose-name",
    "invalid-compose-row",
    "invalid-compose-whitespace",
    "invalid-owner-whitespace",
    "project-without-resources",
    "missing-clone",
    "missing-checkout",
    "invalid-label-json",
    "invalid-label-type",
    "late-unreadable",
    "legacy-project",
    "missing-project-clone",
    "missing-project-checkout",
    "mixed-project-clones",
    "mixed-project-checkouts",
    "foreign-project-late-invalid",
    "live-project-late-invalid",
    "changed-livekit-owner",
    "changed-compose-owner",
    "rm-failure",
    "rm-conditional-failure",
    "down-conditional-failure",
    "down-failure",
    "unknown-kind",
    "compose-acceptance-overlap",
    "orphan-overlap",
    "overlap-existence-failure",
    "non-acceptance-survives",
]
cases += [
    f"{prefix}-{kind}"
    for prefix in ("resource-enumeration-failure", "late-project-unreadable")
    for kind in ("container", "volume", "network")
]
selected = sys.argv[2:] if sys.argv[1:2] == ["--case"] else cases
assert all(x in cases for x in selected), selected
with tempfile.TemporaryDirectory(prefix="dr-sweep-") as tmp:
    repo = pathlib.Path(tmp)
    (repo / "scripts").mkdir()
    (repo / "bin").mkdir()
    for name in ("worktree-common.sh", "worktree-docker.sh", "teardown-worktree.sh"):
        shutil.copy(
            root / "scripts" / name,
            repo / "scripts" / name,
        )
    shutil.copy(root / "docker-compose.yml", repo / "docker-compose.yml")

    def git(*a):
        return subprocess.check_output(["git", "-C", str(repo), *a], text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("add", ".")
    git("commit", "-qm", "fixture")
    import hashlib

    clone = hashlib.sha256(git("rev-parse", "--absolute-git-dir").encode()).hexdigest()[
        :12
    ]
    live = clone
    deadpath = repo / "dead"
    git("worktree", "add", "-qb", "dead", str(deadpath))
    dead = hashlib.sha256(
        subprocess.check_output(
            ["git", "-C", str(deadpath), "rev-parse", "--absolute-git-dir"], text=True
        )
        .strip()
        .encode()
    ).hexdigest()[:12]
    shutil.rmtree(deadpath)
    git("worktree", "prune")
    (repo / "bin/docker").write_text(STUB)
    (repo / "bin/docker").chmod(0o755)
    for case in selected:
        d = {"projects": [], "resources": {}, "mutations": []}
        expected = []
        refuse = False

        def add(
            id,
            checkout=dead,
            owner=clone,
            project=None,
            marker=True,
            kind="container",
            **extra,
        ):
            labels = {
                "com.divineruin.clone": owner,
                "com.divineruin.checkout": checkout,
            }
            if marker:
                labels["divineruin.acceptance"] = "1"
            if project:
                labels["com.docker.compose.project"] = project
            d["resources"][id] = {"kind": kind, "labels": labels, **extra}

        def project():
            d["projects"] = ["stale"]
            add("project", project="stale", marker=False)
            expected.append("down stale")

        if case not in (
            "both-empty",
            "foreign-only",
            "compose-only",
            "down-failure",
            "changed-compose-owner",
        ):
            add("dead")
            expected = ["rm dead"]
        if (
            case
            in (
                "mixed",
                "compose-only",
                "late-unreadable",
                "changed-compose-owner",
                "down-failure",
                "compose-acceptance-overlap",
                "orphan-overlap",
                "overlap-existence-failure",
            )
            or "project" in case
            or case.startswith("resource-")
        ):
            project()
        if case == "mixed":
            add("live", live)
            add("foreign", owner="foreign")
            d["projects"] += ["live-project", "foreign-project"]
            add("live-project", live, project="live-project", marker=False)
            add(
                "foreign-project",
                owner="foreign",
                project="foreign-project",
                marker=False,
            )
        if case == "multiple":
            add("dead2")
            expected.append("rm dead2")
        if case == "owned-live-only":
            d["resources"] = {}
            add("live", live)
            expected = []
        if case == "foreign-only":
            add("foreign", owner="foreign")
            expected = []
            refuse = True
        if case == "both-empty":
            refuse = True
        if case in (
            "compose-failure",
            "container-failure",
            "rm-failure",
            "rm-conditional-failure",
            "down-conditional-failure",
            "down-failure",
        ):
            d["fail"] = case.split("-")[0]
            refuse = True
        if case == "down-conditional-failure":
            project()
        if case == "invalid-compose-json":
            d["listing"] = "{}"
            refuse = True
        if case.startswith("invalid-compose-") and case != "invalid-compose-json":
            d["listing"] = json.dumps(
                [{"Name": ""}]
                if case.endswith("name")
                else ["bad"]
                if case.endswith("row")
                else [{"Name": "bad\tname"}]
            )
            refuse = True
        if case == "invalid-owner-whitespace":
            add("bad", owner="bad\towner")
            refuse = True
        if case == "project-without-resources":
            del d["resources"]["project"]
            refuse = True
        if case in ("missing-clone", "missing-checkout"):
            add("bad")
            del d["resources"]["bad"]["labels"]["com.divineruin." + case[8:]]
            refuse = True
        if case == "invalid-label-json":
            add("bad", raw="{")
            refuse = True
        if case == "invalid-label-type":
            add("bad")
            d["resources"]["bad"]["labels"]["com.divineruin.clone"] = 42
            refuse = True
        if case == "late-unreadable":
            add("bad", unreadable=True)
            refuse = True
        if case in (
            "legacy-project",
            "missing-project-clone",
            "missing-project-checkout",
        ):
            if case == "legacy-project":
                d["resources"]["project"]["labels"] = {
                    "com.docker.compose.project": "stale"
                }
            else:
                del d["resources"]["project"]["labels"][
                    "com.divineruin." + case.rsplit("-", 1)[1]
                ]
            refuse = True
        if case.startswith("mixed-project-"):
            add(
                "other",
                owner="other" if case.endswith("clones") else clone,
                checkout="other" if case.endswith("checkouts") else dead,
                project="stale",
                marker=False,
            )
            refuse = True
        if case in ("foreign-project-late-invalid", "live-project-late-invalid"):
            d["resources"]["project"]["labels"].update(
                {
                    "com.divineruin.clone": "foreign"
                    if case.startswith("foreign")
                    else clone,
                    "com.divineruin.checkout": live,
                }
            )
            add("other", project="stale", marker=False, unreadable=True)
            refuse = True
        if case.startswith("late-project-unreadable-"):
            add(
                "bad",
                project="stale",
                marker=False,
                kind=case.rsplit("-", 1)[1],
                unreadable=True,
            )
            refuse = True
        if case.startswith("resource-enumeration-failure-"):
            add("volume", project="stale", marker=False, kind="volume")
            add("network", project="stale", marker=False, kind="network")
            d["fail"] = "resource-" + case.rsplit("-", 1)[1]
            refuse = True
        if case.startswith("changed-"):
            d["resources"]["dead" if "livekit" in case else "project"]["change"] = True
            refuse = True
        if case in (
            "compose-acceptance-overlap",
            "orphan-overlap",
            "overlap-existence-failure",
        ):
            del d["resources"]["dead"]
            add("dead", project="stale", orphan=case != "compose-acceptance-overlap")
            if case == "compose-acceptance-overlap":
                expected = ["down stale"]
            if case == "overlap-existence-failure":
                d["fail"] = "existence"
                refuse = True
        if case == "non-acceptance-survives":
            add("unmarked", marker=False)
        if case.startswith(
            (
                "late-project-",
                "mixed-project-",
                "foreign-project-",
                "live-project-",
                "legacy-project",
                "missing-project-",
            )
        ):
            d["projects"].insert(0, "earlier")
            add("earlier", project="earlier", marker=False)
        state = repo / "state.json"
        state.write_text(json.dumps(d))
        env = {
            **os.environ,
            "PATH": str(repo / "bin") + ":" + os.environ["PATH"],
            "STATE": str(state),
        }
        command = ["bash", "scripts/teardown-worktree.sh", "--sweep"]
        if "conditional" in case:
            command = [
                "bash",
                "-c",
                "if source scripts/teardown-worktree.sh --sweep; then exit 0; else exit 1; fi",
                "scripts/teardown-worktree.sh",
            ]
        if case == "unknown-kind":
            command = [
                "bash",
                "scripts/worktree-common.sh",
                "destroy-candidate",
                "invalid",
                "dead",
                dead,
            ]
            refuse = True
        r = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True)
        actual = json.loads(state.read_text())["mutations"]
        if refuse:
            diagnostic = (
                "enumeration"
                if ("failure" in case and not case.startswith(("rm-", "down-")))
                or case.startswith("invalid-compose-")
                else "nothing usable"
                if case in ("both-empty", "foreign-only")
                else "mixed ownership"
                if case.startswith("mixed-project-")
                else "no ownership resources"
                if case == "project-without-resources"
                else "unknown sweep candidate kind"
                if case == "unknown-kind"
                else "ownership labels are invalid"
                if case
                in (
                    "legacy-project",
                    "missing-project-clone",
                    "missing-project-checkout",
                )
                else "ownership"
                if not case.startswith(("rm-", "down-"))
                else ""
            )
            assert diagnostic in r.stderr, f"{case}: wrong refusal: {r.stderr}"
        partial = (
            case.startswith(("changed-", "rm-", "down-"))
            or case == "overlap-existence-failure"
        )
        if partial:
            attempted = (
                ["rm dead"]
                if case.startswith("rm-")
                else ["down stale"]
                if case.startswith("down-") or case == "overlap-existence-failure"
                else []
            )
            assert actual == attempted, f"{case}: wrong attempted mutations: {actual}"
        if refuse:
            assert r.returncode != 0, f"{case}: refusal succeeded; mutations={actual}"
            if not partial:
                assert not actual, f"{case}: mutated before refusal: {actual}"
        else:
            assert r.returncode == 0 and sorted(actual) == sorted(expected), (
                f"{case}: expected {expected}, got {actual}; {r.stderr}"
            )
        print("PASS: " + case)
PY
