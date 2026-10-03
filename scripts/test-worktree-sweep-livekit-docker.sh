#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT REAL_DOCKER="$(command -v docker)"
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
unset DATABASE_URL REDIS_URL
"$REAL_DOCKER" info >/dev/null
"$REAL_DOCKER" compose version >/dev/null
python3 -u - "$@" <<'PY'
import hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, uuid

root = pathlib.Path(os.environ["ROOT"])
docker = os.environ["REAL_DOCKER"]
run = "dr-sweep-" + uuid.uuid4().hex[:12]


def real(*args, check=True):
    r = subprocess.run([docker, *args], text=True, capture_output=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr)
    return r


ADAPTER = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path

a = sys.argv[1:]
d = json.loads(Path(os.environ["ISOLATION"]).read_text())
command = [os.environ["REAL_DOCKER"]]
if a[:2] == ["compose", "ls"]:
    r = subprocess.run(command + a, text=True, capture_output=True)
    if r.returncode:
        sys.exit(r.returncode)
    print(json.dumps(sorted([x for x in json.loads(r.stdout) if x["Name"] in d["projects"]], key=lambda x: x["Name"])))
    sys.exit()
if a[:2] == ["ps", "-aq"] and (len(a)==2 or any("divineruin.acceptance" in x for x in a)):
    with open(d["record"], "a") as f:
        f.write(
            (
                "marker-only"
                if a == ["ps", "-aq", "--filter", "label=divineruin.acceptance=1"]
                else "filtered-discovery"
            )
            + "\n"
        )
    a += ["--filter", "label=divineruin.sweep-test=" + d["run"]]
if a[0] == "inspect" and d.get("unreadable", "").startswith(a[-1]):
    sys.exit(1)
if a[0] == "rm" or (a[0] == "compose" and a[-2:] == ["down", "-v"]):
    with open(d["record"], "a") as f:
        f.write("mutation " + str(a) + "\n")
os.execv(command[0], command + a)
"""
cases = [
    "mixed",
    "livekit-only",
    "missing-clone",
    "missing-checkout",
    "late-unreadable",
    "mixed-project-clones",
    "mixed-project-checkouts",
    "compose-acceptance-overlap",
]
selected = sys.argv[2:] if sys.argv[1:2] == ["--case"] else cases
assert all(x in cases for x in selected)
with tempfile.TemporaryDirectory(prefix="dr-sweep-real-") as tmp:
    repo = pathlib.Path(tmp)
    (repo / "scripts").mkdir()
    (repo / "bin").mkdir()
    for name in ("worktree-common.sh", "worktree-docker.sh", "teardown-worktree.sh"):
        shutil.copy(
            root / "scripts" / name,
            repo / "scripts" / name,
        )

    def git(*a):
        return subprocess.check_output(["git", "-C", str(repo), *a], text=True).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("add", ".")
    git("commit", "-qm", "fixture")
    foreignrepo = repo / "foreign"
    foreignrepo.mkdir()
    subprocess.run(["git", "init", "-q", str(foreignrepo)], check=True)
    foreign = hashlib.sha256(
        subprocess.check_output(
            ["git", "-C", str(foreignrepo), "rev-parse", "--absolute-git-dir"],
            text=True,
        )
        .strip()
        .encode()
    ).hexdigest()[:12]
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
    (repo / "bin/docker").write_text(ADAPTER)
    (repo / "bin/docker").chmod(0o755)
    image = "alpine:3.21"
    real("image", "inspect", image, check=False)
    if real("image", "inspect", image, check=False).returncode:
        real("pull", image)

    def exists(id):
        return real("inspect", id, check=False).returncode == 0

    def running(id):
        result = real("inspect", "--format", "{{.State.Running}}", id, check=False)
        if result.returncode and "no such object:" not in result.stderr.lower():
            raise RuntimeError(result.stderr)
        return result.returncode == 0 and result.stdout.strip() == "true"

    for case in selected:
        variants = (
            ("removed", "orphan")
            if case == "compose-acceptance-overlap"
            else ("normal",)
        )
        for variant in variants:
            project = run + "-" + case
            created = []
            record = repo / "record"
            record.write_text("")
            iso = {"projects": [], "run": run, "record": str(record)}

            def labels(owner=clone, checkout=dead, marker=True):
                d = {
                    "com.divineruin.clone": owner,
                    "com.divineruin.checkout": checkout,
                    "divineruin.sweep-test": run,
                }
                if marker:
                    d["divineruin.acceptance"] = "1"
                return d

            def container(d):
                args = ["run", "-d"]
                for k, v in d.items():
                    args += ["--label", k + "=" + v]
                id = real(*args, image, "sleep", "300").stdout.strip()
                created.append(id)
                return id

            config = repo / "docker-compose.yml"
            try:
                stale = container(labels())
                kept = [
                    container(labels(checkout=live)),
                    container(labels(owner=foreign)),
                    container(labels(marker=False)),
                ]
                refuse = case in (
                    "missing-clone",
                    "missing-checkout",
                    "late-unreadable",
                    "mixed-project-clones",
                    "mixed-project-checkouts",
                )
                if case.startswith("missing-"):
                    bad = labels(owner=foreign)
                    del bad["com.divineruin." + case[8:]]
                    kept.append(container(bad))
                if case == "late-unreadable":
                    iso["unreadable"] = container(labels())
                    kept.append(iso["unreadable"])
                if case != "livekit-only":
                    iso["projects"] = [project]
                    services = {
                        "base": {
                            "image": image,
                            "command": ["sleep", "300"],
                            "labels": labels(marker=False),
                        }
                    }
                    if case.startswith("mixed-project-"):
                        services["other"] = {
                            "image": image,
                            "command": ["sleep", "300"],
                            "labels": labels(
                                owner="other" if case.endswith("clones") else clone,
                                checkout="other"
                                if case.endswith("checkouts")
                                else dead,
                                marker=False,
                            ),
                        }
                    if case == "compose-acceptance-overlap":
                        services["acceptance"] = {
                            "image": image,
                            "command": ["sleep", "300"],
                            "labels": labels(),
                        }
                    data = {
                        "services": services,
                        "networks": {"default": {"labels": labels(marker=False)}},
                    }
                    if case.startswith("mixed-project-"):
                        earlier = run + "-aaa"
                        iso["projects"].append(earlier)
                        clean = {
                            "services": {"base": services["base"]},
                            "networks": data["networks"],
                        }
                        config.write_text(json.dumps(clean))
                        real("compose", "-f", str(config), "-p", earlier, "up", "-d")
                        created += real(
                            "ps",
                            "-aq",
                            "--filter",
                            "label=com.docker.compose.project=" + earlier,
                        ).stdout.split()
                    config.write_text(json.dumps(data))
                    real("compose", "-f", str(config), "-p", project, "up", "-d")
                    projectids = real(
                        "ps",
                        "-aq",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ).stdout.split()
                    created += projectids
                    if variant == "orphan":
                        del data["services"]["acceptance"]
                        config.write_text(json.dumps(data))
                else:
                    config.write_text(
                        json.dumps({"services": {"base": {"image": image}}})
                    )
                    projectids = []
                isolation = repo / "isolation"
                isolation.write_text(json.dumps(iso))
                env = {
                    **os.environ,
                    "ISOLATION": str(isolation),
                    "PATH": str(repo / "bin") + ":" + os.environ["PATH"],
                }
                result = subprocess.run(
                    ["bash", "scripts/teardown-worktree.sh", "--sweep"],
                    cwd=repo,
                    env=env,
                    text=True,
                    capture_output=True,
                )
                if refuse:
                    assert result.returncode != 0, (
                        case + ": sweep accepted invalid ownership"
                    )
                    assert "ownership" in result.stderr, (
                        case + ": wrong refusal: " + result.stderr
                    )
                    assert "mutation " not in record.read_text() and all(
                        running(x) for x in created
                    ), case + ": deletion before refusal"
                else:
                    assert result.returncode == 0, case + ": " + result.stderr
                    assert not exists(stale) and all(
                        not exists(x) for x in projectids
                    ), case + ": stale container survived"
                    assert all(running(x) for x in kept), (
                        case + ": protected container removed"
                    )
                assert record.read_text().count("marker-only") == 1, (
                    case + ": marker-only discovery not executed"
                )
                print("PASS: " + case + " " + variant)
            finally:
                for id in created:
                    real("rm", "-f", id, check=False)
                for cleanup_project in iso["projects"]:
                    real(
                        "compose",
                        "-f",
                        str(config),
                        "-p",
                        cleanup_project,
                        "down",
                        "-v",
                        "--remove-orphans",
                        check=False,
                    )
PY
