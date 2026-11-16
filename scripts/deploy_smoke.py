import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

import deploy_smoke_config as config_smoke
import deploy_smoke_server as server_smoke
from deploy_smoke_images import image_sources

mode = sys.argv[1]
if mode in ("agent", "migrate", "media"):
    import deploy_smoke_agent as agent_smoke
if mode == "media":
    import deploy_smoke_media as media_smoke
if mode == "migrate":
    import deploy_smoke_migrate as migrate_smoke

root = pathlib.Path.cwd()
run_id = uuid.uuid4().hex[:12]
project = "dr-smoke-" + os.environ["WT_CHECKOUT_ID"] + "-" + run_id
name = "smoke_" + run_id
key = name + ":sentinel"
tmp = pathlib.Path(tempfile.mkdtemp(prefix="dr-smoke-"))
os.chmod(tmp, 0o700)
children = []
created_db = False
compose_started = False
sentinel = False
exports = []
built_images = []
log = open(tmp / "run.log", "w+")  # noqa: SIM115 — closed after ordered teardown, before artifact redaction
env = dict(os.environ)
base_db = env["SMOKE_DB"]
base_redis = env["SMOKE_REDIS"]
fixture_db = urllib.parse.urlsplit(base_db)._replace(path="/" + name).geturl()
private_values = [base_db, base_redis, fixture_db]
# worktree-common.sh exports the CHECKOUT's COMPOSE_PROJECT_NAME; a child that omits -p must not resolve to it.
env.update(
    DEPLOY_ENV_FILE=str(tmp / "runtime.env"),
    DEPLOY_HTTP_PORT="0",
    COMPOSE_PROJECT_NAME=project,
)
compose = [
    "docker",
    "compose",
    "-p",
    project,
    "-f",
    str(root / "deploy/compose.yml"),
    "-f",
    str(tmp / "override.json"),
]


def command(args, *, capture=False, input=None, settings=None, merged=False, deadline=300):
    if args[:2] == ["docker", "compose"]:
        log.write("compose args: " + repr(args) + "\n")
        log.flush()
    result = subprocess.run(
        args,
        input=input,
        text=True,
        env=settings or env,
        stdout=subprocess.PIPE if capture else log,
        stderr=subprocess.STDOUT if merged else log,
        timeout=deadline,
    )
    if result.returncode:
        raise RuntimeError(f"{args[0:2]} exited {result.returncode}; see smoke log")
    return result.stdout.strip() if capture else None


def authorize():
    command(
        [
            "bash",
            "-c",
            'source scripts/worktree-common.sh; wt_authorize connect; wt_validate_resources "$COMPOSE_PROJECT_NAME"',
        ]
    )


def bun(code, db=fixture_db):
    authorize()
    settings = dict(env, DATABASE_URL=db, REDIS_URL=base_redis, SMOKE_KEY=key)
    return command(
        ["bun", "--no-env-file", "run", "-"],
        capture=True,
        input=code,
        settings=settings,
    )


def proxy_url(original, port):
    parts = urllib.parse.urlsplit(original)
    credentials, marker, _ = parts.netloc.rpartition("@")
    return parts._replace(netloc=credentials + marker + f"proxy:{port}").geturl()


def inspect(resource):
    return json.loads(command(["docker", "inspect", resource], capture=True))[0]


def http(url, body=None, method=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    start = time.monotonic()
    try:
        response = urllib.request.urlopen(req, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        data = response.read()
        return (
            response.status,
            json.loads(data) if data else None,
            time.monotonic() - start,
        )


def ready(url, process=None):
    for _ in range(120):
        if process and process.poll() is not None:
            raise RuntimeError("host server exited before readiness")
        try:
            if http(url + "/api/me")[0] == 401:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("server readiness deadline expired")


health_calls = []


def health(url, failed=None):
    now = time.monotonic()
    health_calls[:] = [t for t in health_calls if now - t < 60]
    assert len(health_calls) < 30, "health smoke exceeds rate limit budget"
    health_calls.append(now)
    status, body, elapsed = http(url + "/api/health")
    expected = {
        "status": "unavailable" if failed else "ok",
        "dependencies": {dep: "unavailable" if dep == failed else "ok" for dep in ("postgres", "valkey")},
    }
    print(f"health {failed or 'healthy'}: {status} {body} {elapsed:.3f}s", flush=True)
    assert status == (503 if failed else 200) and body == expected and elapsed < 2


def host(args, settings):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = dict(settings, PORT=str(port))
    child = subprocess.Popen(args, env=settings, stdout=log, stderr=log, start_new_session=True)
    children.append(child)
    url = f"http://127.0.0.1:{port}"
    ready(url, child)
    return child, url


def stop(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def main():
    global created_db, compose_started, sentinel
    authorize()
    upstreams = {}
    for service in ("postgres", "valkey"):
        ids = command(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + env["SMOKE_OWNER"],
                "--filter",
                "label=com.docker.compose.service=" + service,
            ],
            capture=True,
        ).splitlines()
        assert len(ids) == 1
        upstreams[service] = inspect(ids[0])
    common = set(upstreams["postgres"]["NetworkSettings"]["Networks"]) & set(
        upstreams["valkey"]["NetworkSettings"]["Networks"]
    )
    assert len(common) == 1, "expected one common checkout-owned network"
    network = common.pop()
    labels = inspect(network)["Labels"]
    for suffix in ("clone", "checkout"):
        assert labels["com.divineruin." + suffix] == env["WT_" + suffix.upper() + "_ID"]
    override = {
        "services": {
            "server": {"networks": ["default"]},
            "proxy": {
                "image": "ghcr.io/shopify/toxiproxy:2.12.0",
                "ports": ["127.0.0.1::8474"],
                "networks": ["default", "checkout"],
            },
        },
        "networks": {"checkout": {"external": True, "name": network}},
    }
    if mode in ("agent", "migrate", "media"):
        agent_smoke.configure(override, project)
    if mode == "media":
        media_smoke.configure(sys.modules[__name__], override)
    (tmp / "override.json").write_text(json.dumps(override))
    settings = {
        "DATABASE_URL": proxy_url(fixture_db, 15432),
        "REDIS_URL": proxy_url(base_redis, 16379),
        "JWT_SECRET": uuid.uuid4().hex + uuid.uuid4().hex,
        "INTERNAL_SECRET": uuid.uuid4().hex,
        "CORS_ORIGIN": "https://smoke.invalid",
        "NODE_ENV": "production",
        "PORT": "3001",
        "MEDIA_DIR": "/var/lib/divineruin/media",
        "LIVEKIT_URL": "ws://127.0.0.1:1",
        "LIVEKIT_API_KEY": "smoke-LIVEKIT_API_KEY-01234567890123456789012345678901",
        "LIVEKIT_API_SECRET": "smoke-LIVEKIT_API_SECRET-01234567890123456789012345678901",
        "GEMINI_API_KEY": "smoke-GEMINI_API_KEY",
        "RESEND_API_KEY": "smoke-RESEND_API_KEY",
    }
    if mode in ("agent", "migrate", "media"):
        settings.update(agent_smoke.environment())
    private_values.extend(settings[k] for k in ("DATABASE_URL", "REDIS_URL", "JWT_SECRET", "INTERNAL_SECRET"))
    (tmp / "runtime.env").write_text("".join(k + "=" + v + "\n" for k, v in settings.items()))
    os.chmod(tmp / "runtime.env", 0o600)
    compose_started = True
    images = {}
    if mode != "migrate":
        targets = ("server", "agent") if mode == "media" else ("server" if mode == "config" else mode,)
        command([*compose, "build", *targets], deadline=900)
        for target in targets:
            image = project + "-" + target
            images[target] = image
            built_images.append(image)
            print(
                "image "
                + command(
                    ["docker", "image", "inspect", "--format", "{{.Id}}", image],
                    capture=True,
                ),
                flush=True,
            )
            uid = command(
                ["docker", "run", "--rm", "--entrypoint", "id", image, "-u"],
                capture=True,
            )
            assert uid.isdigit() and int(uid) > 0, "image must execute as non-root"
            if target == "agent":
                agent_smoke.image_checks(sys.modules[__name__], image, uid)
            else:
                image_sources(sys.modules[__name__], image)
    bun(
        'const s = new Bun.SQL(process.env.DATABASE_URL); await s.unsafe(`CREATE DATABASE "'
        + name
        + '"`); await s.close();',
        base_db,
    )
    created_db = True
    if mode != "migrate":
        authorize()
        fixture_env = dict(env, DATABASE_URL=fixture_db, REDIS_URL=base_redis)
        command(["bun", "--no-env-file", "run", "scripts/migrate.ts"], settings=fixture_env)
        authorize()
        command(
            [
                "uv",
                "run",
                "--project",
                "scripts",
                "--frozen",
                "python",
                "scripts/seed_content.py",
            ],
            settings=fixture_env,
        )
    bun(
        'const r = new Bun.RedisClient(process.env.REDIS_URL); await r.set(process.env.SMOKE_KEY,"alive","EX",1800); r.close();'
    )
    sentinel = True
    if mode in ("server", "config"):
        fixture = server_smoke.fixture(sys.modules[__name__])
    compose_started = True
    command([*compose, "up", "-d", "proxy"])
    proxy_port = command([*compose, "port", "proxy", "8474"], capture=True).rsplit(":", 1)[1]
    proxy = "http://127.0.0.1:" + proxy_port
    for _ in range(60):
        try:
            if http(proxy + "/version")[0] == 200:
                break
        except OSError:
            time.sleep(0.25)
    for dep, port, upstream_port in [
        ("postgres", 15432, 5432),
        ("valkey", 16379, 6379),
    ]:
        assert (
            http(
                proxy + "/proxies",
                {
                    "name": dep,
                    "listen": f"0.0.0.0:{port}",
                    "upstream": upstreams[dep]["NetworkSettings"]["Networks"][network]["IPAddress"]
                    + ":"
                    + str(upstream_port),
                },
            )[0]
            == 201
        )
    if mode == "media":
        media_smoke.run(sys.modules[__name__], images, settings)
    elif mode == "migrate":
        migrate_smoke.run(sys.modules[__name__], override)
    elif mode == "agent":
        agent_smoke.run(sys.modules[__name__], proxy, image)
    else:
        server_smoke.run(sys.modules[__name__], settings, fixture, proxy)
    authorize()
    for original in upstreams.values():
        current = inspect(original["Id"])
        assert current["State"]["Running"] and current["State"]["StartedAt"] == original["State"]["StartedAt"]
    assert (
        bun(
            "const r = new Bun.RedisClient(process.env.REDIS_URL); console.log(await r.get(process.env.SMOKE_KEY)); r.close();"
        )
        == "alive"
    )
    authorize()
    if mode in ("server", "config"):
        server_smoke.development(sys.modules[__name__], fixture)
        if mode == "config":
            config_smoke.run(sys.modules[__name__], images["server"], settings)
    else:
        print(mode + " smoke passed", flush=True)


def cleanup_compose():
    resolved = json.loads(command([*compose, "config", "--format", "json"], capture=True))
    if resolved["name"] != project:
        raise RuntimeError("smoke cleanup refused a different Compose project")
    try:
        command([*compose, "logs", "--no-color"])
    finally:
        command([*compose, "down", "--volumes", "--remove-orphans"])


def interrupt(signum, frame):
    raise RuntimeError("smoke interrupted")


signal.signal(signal.SIGTERM, interrupt)
signal.signal(signal.SIGINT, interrupt)
failed = False
try:
    main()
except Exception as error:
    traceback.print_exc(file=log)
    print(f"smoke failed: {error}", flush=True)
    failed = True
finally:
    actions = [lambda child=child: stop(child) for child in children]
    if compose_started:
        actions.append(cleanup_compose)
    actions.extend(lambda container=container: command(["docker", "rm", "-f", container]) for container in exports)
    actions.extend(lambda image=image: command(["docker", "image", "rm", image]) for image in built_images)
    if sentinel:
        actions.append(
            lambda: bun(
                "const r = new Bun.RedisClient(process.env.REDIS_URL); await r.del(process.env.SMOKE_KEY); r.close();"
            )
        )
    if created_db:
        actions.append(
            lambda: bun(
                'const s = new Bun.SQL(process.env.DATABASE_URL); await s.unsafe(`DROP DATABASE "'
                + name
                + '" WITH (FORCE)`); await s.close();',
                base_db,
            )
        )
    for action in actions:
        try:
            action()
        except Exception as error:
            print(f"cleanup failed: {error}", flush=True)
            failed = True
    log.close()
    if failed:
        destination = root / "flake-artifacts" / project
        destination.mkdir(parents=True, exist_ok=True)
        content = (tmp / "run.log").read_text(errors="replace")
        for secret in private_values:
            if secret:
                content = content.replace(secret, "[redacted]")
        (destination / "smoke.log").write_text(content)
        print("log: " + str(destination / "smoke.log"), flush=True)
    shutil.rmtree(tmp)
raise SystemExit(1 if failed else 0)
