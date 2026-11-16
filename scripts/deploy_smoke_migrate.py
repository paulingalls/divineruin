"""Exercise the operator deployment boundary against an isolated database."""

import ast
import json
import shutil
import socket
import subprocess
import time

from deploy_smoke_server import fixture

SERVICES = ("server", "agent", "worker")


def run(h, override):
    tree = ast.parse((h.root / "scripts/seed_content.py").read_text())
    tables = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TABLE_MAP" for t in n.targets)
    )
    corpus = h.tmp / "content"
    shutil.copytree(h.root / "content", corpus)
    nodes_path = corpus / "gathering_nodes.json"
    valid_nodes = nodes_path.read_text()
    override["services"]["migrate"] = {"volumes": [str(corpus) + ":/app/content:ro"]}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        h.env["DEPLOY_HTTP_PORT"] = str(sock.getsockname()[1])
    url = "http://127.0.0.1:" + h.env["DEPLOY_HTTP_PORT"]
    event_file = h.tmp / "events.jsonl"
    stream = event_file.open("w")
    events = subprocess.Popen(
        [
            "docker",
            "events",
            "--format",
            "{{json .}}",
            "--filter",
            "label=com.docker.compose.project=" + h.project,
        ],
        stdout=stream,
        stderr=h.log,
        start_new_session=True,
    )
    h.children.append(events)
    h.built_images.extend(h.project + "-" + service for service in ("server", "agent", "migrate"))
    seen_jobs = set()

    def configure(changed=False):
        if changed:
            for service in SERVICES:
                override["services"].setdefault(service, {})["build"] = {
                    "labels": {"com.divineruin.smoke-revision": h.run_id}
                }
        (h.tmp / "override.json").write_text(json.dumps(override))

    def invalid():
        nodes = json.loads(valid_nodes)
        nodes[0]["location_id"] = "missing_smoke_location"
        nodes_path.write_text(json.dumps(nodes))

    def all_events():
        return [json.loads(line) for line in event_file.read_text().splitlines() if line.strip()]

    def serving():
        result = {}
        for service in SERVICES:
            ids = h.command([*h.compose, "ps", "-a", "-q", service], capture=True).splitlines()
            if ids:
                assert len(ids) == 1
                info = h.inspect(ids[0])
                result[service] = (
                    info["Id"],
                    info["Image"],
                    info["State"]["StartedAt"],
                )
        return result

    def snapshot():
        state = json.loads(
            h.bun("""
const s = new Bun.SQL(process.env.DATABASE_URL);
const tables = await s`SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename`;
const result = {};
for (const {tablename: t} of tables) {
  result[t] = await s.unsafe('SELECT row_to_json(t) AS row FROM "' + t + '" t ORDER BY row_to_json(t)::text');
}
console.log(JSON.stringify(result)); await s.close();
""")
        )
        return {t: state[t] for t in set(tables.values()) | {"player_map_progress", "_migrations"}}

    def no_listener():
        try:
            h.http(url + "/api/health")
        except OSError:
            return
        raise AssertionError("health route reachable before successful deployment")

    def deploy(
        success,
        keep_healthy=False,
        error="unknown location_id 'missing_smoke_location'",
    ):
        output_path = h.tmp / ("attempt-" + str(len(seen_jobs)) + ".log")
        with output_path.open("w") as output:
            child = subprocess.Popen(
                [
                    "bash",
                    "scripts/deploy-up.sh",
                    "-p",
                    h.project,
                    "-f",
                    str(h.tmp / "override.json"),
                ],
                env=h.env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            h.children.append(child)
            deadline = time.monotonic() + 900
            next_probe = 0
            while child.poll() is None:
                assert time.monotonic() < deadline, "deploy deadline expired"
                if keep_healthy and time.monotonic() >= next_probe:
                    h.health(url)
                    next_probe = time.monotonic() + 5
                time.sleep(0.2)
        output = output_path.read_text()
        h.log.write(output)
        h.log.flush()
        assert (child.returncode == 0) == success, output
        if success:
            assert "Seed mode: production" in output and "all validations passed" in output
        else:
            assert error in output, output
        deadline = time.monotonic() + 5
        while True:
            recorded = all_events()
            jobs = [
                e
                for e in recorded
                if e.get("Action") == "die"
                and e["Actor"]["Attributes"].get("com.docker.compose.service") == "migrate"
                and e["Actor"]["Attributes"].get("com.docker.compose.oneoff") == "True"
                and e["Actor"]["ID"] not in seen_jobs
            ]
            if jobs or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        assert len(jobs) == 1, jobs
        job = jobs[0]
        seen_jobs.add(job["Actor"]["ID"])
        assert job["Actor"]["Attributes"]["exitCode"] == ("0" if success else "1")
        print(
            "migrate execution " + job["Actor"]["ID"][:12] + (" succeeded" if success else " refused"),
            flush=True,
        )
        return job, output

    def assert_content():
        expected_migrations = sorted(p.name for p in (h.root / "scripts/migrations").glob("*.sql"))
        migrations = json.loads(
            h.bun("""
const s = new Bun.SQL(process.env.DATABASE_URL);
console.log(JSON.stringify((await s`SELECT name FROM _migrations ORDER BY name`).map(r => r.name)));
await s.close();
""")
        )
        assert migrations == expected_migrations and migrations
        state = snapshot()
        assert state["players"] == state["player_map_progress"] == []
        for filename, table in tables.items():
            if table == "players":
                continue
            authored = json.loads((h.root / "content" / filename).read_text())
            actual = [r["row"]["data"] for r in state[table]]
            assert authored and len(authored) == len(actual) and all(row in actual for row in authored), table
        return state

    try:
        configure()
        resolved = json.loads(h.command([*h.compose, "config", "--format", "json"], capture=True))
        assert all(
            resolved["services"][s]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
            for s in SERVICES
        )
        no_listener()
        invalid()
        deploy(False)
        uid = h.command(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "id",
                h.project + "-migrate",
                "-u",
            ],
            capture=True,
        )
        assert uid.isdigit() and int(uid) > 0
        assert serving() == {}
        no_listener()
        assert all(not rows for table, rows in snapshot().items() if table != "_migrations"), snapshot()

        nodes_path.write_text(valid_nodes)
        job, _ = deploy(True)
        state = serving()
        assert set(state) == set(SERVICES)
        recorded = all_events()
        starts = [
            e
            for e in recorded
            if e.get("Action") == "start" and e["Actor"]["Attributes"].get("com.docker.compose.service") in SERVICES
        ]
        assert {e["Actor"]["Attributes"]["com.docker.compose.service"] for e in starts} == set(SERVICES)
        assert all(e["timeNano"] > job["timeNano"] for e in starts), "serving started before migration completed"
        print("successful migrate die precedes all three serving starts", flush=True)
        h.ready(url)
        h.health(url)
        for service, marker in (
            ("agent", "failed to connect to livekit"),
            ("worker", "Polling pass complete"),
        ):
            for _ in range(240):
                output = h.command(["docker", "logs", state[service][0]], capture=True, merged=True)
                if marker in output:
                    assert "Preflight resources closed; preflight complete" in output
                    break
                time.sleep(0.5)
            else:
                raise AssertionError(service + " startup marker missing")
        baseline = assert_content()
        migrate_image = h.inspect(h.project + "-migrate")["Id"]
        _, output = deploy(True)
        assert "No new migrations to apply." in output
        assert h.inspect(h.project + "-migrate")["Id"] == migrate_image
        assert snapshot() == baseline
        refreshed = serving()
        assert all(refreshed[service][0] != state[service][0] for service in SERVICES)
        assert all(refreshed[service][1] == state[service][1] for service in SERVICES)
        state = refreshed
        h.ready(url)
        print("unchanged image: fresh job and readers; complete row snapshots unchanged", flush=True)

        configure(changed=True)
        invalid()
        deploy(False, keep_healthy=True)
        assert h.inspect(h.project + "-migrate")["Id"] == migrate_image
        changed = {
            service: h.inspect(h.project + "-" + ("agent" if service == "worker" else service))["Id"]
            for service in SERVICES
        }
        assert all(changed[service] != state[service][1] for service in SERVICES)
        assert serving() == state
        h.health(url)
        assert snapshot() == baseline
        print(
            "changed images: failed job preserved all serving ids, images, start times and health",
            flush=True,
        )

        nodes_path.write_text(valid_nodes)
        roles_path = corpus / "role_archetypes.json"
        valid_roles = roles_path.read_text()
        roles = json.loads(valid_roles)
        roles[0]["default_disposition"] = "invalid-smoke-disposition"
        roles_path.write_text(json.dumps(roles))
        deploy(False, keep_healthy=True, error="default_disposition")
        assert serving() == state
        assert snapshot() == baseline
        h.health(url)
        roles_path.write_text(valid_roles)
        deploy(True)
        h.ready(url)
        h.health(url)
        current = serving()
        assert all(current[service][1] == changed[service] for service in SERVICES)
        assert assert_content() == baseline
        account = fixture(h)
        status, auth, _ = h.http(url + "/api/auth/verify-code", {"email": account["email"], "code": "123456"})
        assert status == 200, auth
        recipes_path = corpus / "recipes.json"
        recipes = json.loads(recipes_path.read_text())
        recipe = recipes[0]

        def recipe_name():
            status, body, _ = h.http(url + "/api/activity-templates", token=auth["token"])
            assert status == 200, body
            return next(
                item["name"] for group in body["groups"] for item in group["items"] if item["id"] == recipe["id"]
            )

        assert recipe_name() == recipe["name"]
        recipe["name"] = "Deployment smoke revised recipe"
        recipes_path.write_text(json.dumps(recipes))
        unchanged_image = h.inspect(h.project + "-server")["Id"]
        deploy(True)
        h.ready(url)
        h.health(url)
        assert h.inspect(h.project + "-server")["Id"] == unchanged_image
        assert recipe_name() == recipe["name"], "HTTP catalog retained pre-deployment recipe"
        print("content-only deployment refreshes the HTTP catalog", flush=True)
        accepted = serving()
        accepted_rows = snapshot()
        override["services"]["migrate"]["environment"] = {"REDIS_URL": "redis://127.0.0.1:1"}
        configure()
        deploy(False, keep_healthy=True, error="Valkey content-cache invalidation failed")
        assert serving() == accepted
        assert snapshot() == accepted_rows
        h.health(url)
        print("cache invalidation failure preserves serving containers", flush=True)
    finally:
        h.stop(events)
        stream.close()
