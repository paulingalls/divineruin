"""Server image, host parity, dependency faults and development CLI smoke."""

import json
import os


def fixture(h):
    fixture = json.loads(
        h.bun("""const s = new Bun.SQL(process.env.DATABASE_URL);
    const [a] = await s`INSERT INTO accounts (email) VALUES (${'smoke-' + process.env.SMOKE_KEY.replaceAll(':', '-') + '@example.invalid'}) RETURNING id, email, created_at`;
    await s`INSERT INTO signin_allowlist(email) VALUES (${a.email})`;
    await s`INSERT INTO auth_codes (account_id, code, expires_at) VALUES (${a.id}, '123456', NOW() + INTERVAL '10 minutes')`;
    console.log(JSON.stringify(a)); await s.close();""")
    )
    return fixture


def run(h, settings, fixture, proxy):
    h.command([*h.compose, "up", "-d", "--no-deps", "server"])
    server_id = h.command([*h.compose, "ps", "-q", "server"], capture=True)
    started = h.inspect(server_id)["State"]["StartedAt"]
    url = "http://127.0.0.1:" + h.command([*h.compose, "port", "server", "3001"], capture=True).rsplit(":", 1)[1]
    h.ready(url)
    h.health(url)
    status, auth, _ = h.http(url + "/api/auth/verify-code", {"email": fixture["email"], "code": "123456"})
    assert status == 200 and auth["account_id"] == fixture["id"]
    token = auth["token"]
    expected = {
        "account_id": fixture["id"],
        "player_id": "player_" + fixture["id"][:8],
        "email": fixture["email"],
        "created_at": fixture["created_at"],
    }

    def me(endpoint):
        status, body, _ = h.http(endpoint + "/api/me", token=token)
        assert status == 200 and body == expected, (status, body)
        assert h.http(endpoint + "/api/me")[0] == 401
        assert h.http(endpoint + "/api/me", token="invalid")[0] == 401

    me(url)
    (h.tmp / "host-media").mkdir()
    baseline, host_url = h.host(
        ["bun", "run", "--cwd", "apps/server", "start"],
        dict(
            h.env,
            **dict(
                settings,
                DATABASE_URL=h.fixture_db,
                JWT_SECRET="ab" * 32,
                REDIS_URL=h.base_redis,
                MEDIA_DIR=str(h.tmp / "host-media"),
            ),
        ),
    )
    h.health(host_url)
    me(host_url)
    h.stop(baseline)
    for dep in ("postgres", "valkey"):
        for fault in ("refusal", "timeout"):
            h.health(url)
            path = proxy + "/proxies/" + dep
            if fault == "refusal":
                assert h.http(path, {"enabled": False})[0] == 200
            else:
                assert (
                    h.http(
                        path + "/toxics",
                        {
                            "name": "blackhole",
                            "type": "timeout",
                            "stream": "downstream",
                            "attributes": {"timeout": 0},
                        },
                    )[0]
                    == 200
                )
            for _ in range(3):
                h.health(url, dep)
            if fault == "refusal":
                assert h.http(path, {"enabled": True})[0] == 200
            else:
                assert h.http(path + "/toxics/blackhole", method="DELETE")[0] == 204
            h.health(url)
    me(url)
    assert h.inspect(server_id)["State"]["StartedAt"] == started


def development(h, account):
    h.bun("""const s = new Bun.SQL(process.env.DATABASE_URL);
await s`INSERT INTO auth_codes (account_id, code, expires_at)
SELECT id, '654321', NOW() + INTERVAL '10 minutes' FROM accounts
WHERE email = ${'smoke-' + process.env.SMOKE_KEY.replaceAll(':', '-') + '@example.invalid'}`;
await s.close();""")
    dev, dev_url = h.host(
        ["bun", "run", "dev:server"],
        dict(
            {k: os.environ[k] for k in ("PATH", "HOME")},
            DATABASE_URL=h.fixture_db,
            REDIS_URL=h.base_redis,
        ),
    )
    h.health(dev_url)
    status, auth, _ = h.http(dev_url + "/api/auth/verify-code", {"email": account["email"], "code": "654321"})
    assert status == 200 and auth["account_id"] == account["id"], (status, auth)
    status, me, _ = h.http(dev_url + "/api/me", token=auth["token"])
    assert status == 200 and me["account_id"] == account["id"] and me["email"] == account["email"], (status, me)
    assert h.http(dev_url + "/api/me")[0] == 401
    h.stop(dev)
    print("server smoke passed", flush=True)
