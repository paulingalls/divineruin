"""Image-boundary deployment checks for the agent and worker."""

import json
import pathlib
import re
import tarfile
import time


def configure(override, project):
    override["networks"]["isolated"] = {"internal": True}
    override["services"]["proxy"]["networks"].append("isolated")
    for service in ("agent", "worker"):
        override["services"][service] = {"image": project + "-agent", "networks": ["isolated"]}


def environment():
    # Read names, never credentials, without importing the agent's dependency graph.
    result = {
        name: "smoke-" + name + "-01234567890123456789012345678901"
        for name in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "DEEPGRAM_API_KEY",
            "INWORLD_API_KEY",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
        )
    }
    source = pathlib.Path("apps/agent/voices.py").read_text()
    for name in re.findall(r'"(INWORLD_VOICE_[A-Z_]+)"', source):
        result[name] = "smoke-" + name
    roles = source.split("_ROLE_ARCHETYPE_IDS: tuple[str, ...] = (", 1)[1].split(")", 1)[0]
    for role in re.findall(r'"([a-z_]+)"', roles):
        result["INWORLD_VOICE_ROLE_" + role.upper()] = "smoke-role-" + role
    result.update(AGENT_ENV="production", LIVEKIT_URL="ws://127.0.0.1:1")
    return result


def image_checks(h, image, uid):
    metadata = h.inspect(image)
    assert metadata["Architecture"] == "amd64"
    for args, expected in [
        (["python", "--version"], "Python " + pathlib.Path(".python-version").read_text().strip()),
        (["ffmpeg", "-version"], "n8.1.3-27-g8dca1586f4"),
    ]:
        output = h.command(["docker", "run", "--rm", "--platform", "linux/amd64", image, *args], capture=True)
        print(output.splitlines()[0], flush=True)
        assert expected in output, output
    print("architecture amd64; uid " + uid, flush=True)
    h.command(
        [
            "docker",
            "run",
            "--rm",
            image,
            "python",
            "-c",
            "from pathlib import Path\nfor d in ('/app/apps/server/audio', '/app/apps/agent/transcripts'):\n    p = Path(d, 'smoke'); p.touch(); p.unlink()",
        ]
    )

    assert not any(re.search(r"(API_KEY|SECRET|TOKEN|PASSWORD)=", item) for item in metadata["Config"]["Env"])
    history = h.command(["docker", "history", "--no-trunc", image], capture=True)
    assert not re.search(r"(API_KEY|SECRET|TOKEN|PASSWORD)=", history)
    container = h.command(["docker", "create", image], capture=True)
    h.exports.append(container)
    archive = h.tmp / "agent-image.tar"
    h.command(["docker", "export", "-o", str(archive), container])
    with tarfile.open(archive) as tree:
        entries = tree.getmembers()
        paths = {entry.name.removeprefix("./") for entry in entries}
        files = {entry.name.removeprefix("./") for entry in entries if entry.isfile() or entry.issym()}
    allowed = {
        "app/" + str(path)
        for pattern in (
            "apps/agent/*.py",
            "apps/agent/pyproject.toml",
            "content/**/*",
            "apps/mobile/assets/sounds/*.mp3",
            "apps/mobile/assets/sounds/textures/*.mp3",
            "assets/audio/prologue.mp3",
        )
        for path in pathlib.Path(".").glob(pattern)
        if path.is_file()
    }
    unexpected = {
        path
        for path in files
        if path.startswith("app/") and not path.startswith("app/apps/agent/.venv/") and path not in allowed
    }
    assert not unexpected, f"unexpected application files: {sorted(unexpected)[:8]}"
    for path in (
        "app/apps/agent/agent.py",
        "app/apps/agent/async_worker.py",
        "app/content/gods.json",
        "app/assets/audio/prologue.mp3",
    ):
        assert path in paths, path
    for source in pathlib.Path("apps/agent").glob("*.py"):
        assert "app/" + str(source) in paths, source
    for path in paths:
        parts = pathlib.PurePosixPath(path).parts
        assert not any(part == ".git" or part == ".env" or part.startswith(".env.") for part in parts), path
        if path.startswith("app/") and ".venv" not in parts:
            assert not set(parts) & {"tests", "fixtures", "test-fixtures", "__tests__"}, path
    archive.unlink()
    h.command(["docker", "rm", container])
    h.exports.remove(container)


def run(h, proxy, image):
    # Seed content only; runtime rows must not invite paid narration in the idle pass.
    counts = h.bun("""const s = new Bun.SQL(process.env.DATABASE_URL);
await s`TRUNCATE players CASCADE`;
await s`TRUNCATE async_activities, training_activities CASCADE`;
const [r] = await s`SELECT (SELECT count(*) FROM players)::int AS players,
(SELECT count(*) FROM async_activities)::int AS activities,
(SELECT count(*) FROM training_activities)::int AS training`;
console.log(JSON.stringify(r)); await s.close();""")
    assert json.loads(counts) == {"players": 0, "activities": 0, "training": 0}

    def case(service, marker, failure=False):
        h.command([*h.compose, "up", "-d", "--force-recreate", "--no-deps", service])
        container = h.command([*h.compose, "ps", "-a", "-q", service], capture=True)
        assert h.inspect(container)["Image"] == h.inspect(image)["Id"]
        deadline = time.monotonic() + 120
        try:
            while time.monotonic() < deadline:
                output = h.command(["docker", "logs", container], capture=True, merged=True)
                if marker in output:
                    if failure:
                        state = h.inspect(container)["State"]
                        if state["Running"]:
                            time.sleep(0.2)
                            continue
                        assert state["ExitCode"] != 0
                        assert "failed to connect to livekit" not in output and "Polling pass complete" not in output
                    else:
                        markers = [
                            "Preflight environment validated",
                            "Preflight Postgres query succeeded",
                            "Preflight content validated",
                            "Preflight Valkey PING succeeded",
                            "Preflight resources closed; preflight complete",
                            marker,
                        ]
                        positions = [output.index(item) for item in markers]
                        assert positions == sorted(positions), output
                        assert h.inspect(container)["State"]["Running"]
                        if service == "worker":
                            assert "Traceback" not in output and "ERROR" not in output
                    print(service + ": " + marker, flush=True)
                    return
                assert h.inspect(container)["State"]["Running"], output
                time.sleep(0.5)
            raise RuntimeError(service + " startup deadline expired")
        finally:
            h.command([*h.compose, "logs", "--no-color", service])
            h.command([*h.compose, "rm", "-s", "-f", service])

    case("agent", "failed to connect to livekit")
    path = proxy + "/proxies/valkey"
    assert h.http(path, {"enabled": False})[0] == 200
    case("agent", "Valkey preflight failed", failure=True)
    assert h.http(path, {"enabled": True})[0] == 200
    case("worker", "Polling pass complete")
    path = proxy + "/proxies/postgres"
    assert h.http(path, {"enabled": False})[0] == 200
    case("worker", "Postgres preflight failed", failure=True)
    assert h.http(path, {"enabled": True})[0] == 200
    h.bun("const s = new Bun.SQL(process.env.DATABASE_URL); await s`DELETE FROM npcs`; await s.close();")
    case("agent", "Content preflight failed: npcs", failure=True)
