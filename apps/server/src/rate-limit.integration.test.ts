import { afterAll, beforeAll, expect, test } from "bun:test";
import { SignJWT } from "jose";
import { codePath, launch, resources, secret } from "./test-fixtures/rate-limit-server.ts";

let data: Awaited<ReturnType<typeof resources>>;
const servers: Awaited<ReturnType<typeof launch>>[] = [];
let a: Awaited<ReturnType<typeof launch>>, b: typeof a;
let next = 1;
const ip = () => `198.18.${Math.floor(next / 250)}.${(next++ % 250) + 1}`;
const headers = (xff: string) => ({ "X-Forwarded-For": xff });
async function variant(hops?: string, bypass?: string) {
  const s = await launch({ TRUSTED_PROXY_HOPS: hops, RATE_LIMIT_BYPASS: bypass });
  servers.push(s);
  return s;
}
async function post(s: typeof a, xff?: string, email?: string) {
  return s.request(codePath, xff === undefined ? {} : headers(xff), {
    email: email ?? (await data.address()),
  });
}
async function allowed(response: Response, body: unknown = { ok: true }) {
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual(body);
}
async function blocked(response: Response) {
  expect(response.status).toBe(429);
  expect(await response.json()).toEqual({ error: "Too many requests" });
  expect(Number(response.headers.get("Retry-After"))).toBeWithin(1, 61);
  expect(response.headers.get("Access-Control-Allow-Origin")).toBeTruthy();
  expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
}
async function bearer(player: string, account = crypto.randomUUID(), expired = false) {
  return `Bearer ${await new SignJWT({ sub: account, pid: player })
    .setProtectedHeader({ alg: "HS256" })
    .setExpirationTime(expired ? 1 : "1h")
    .sign(Buffer.from(secret, "hex"))}`;
}
beforeAll(async () => {
  data = await resources();
  a = await variant("1");
  b = await variant("1");
});
afterAll(async () => {
  await Promise.all(servers.map((s) => s.stop()));
  await data.cleanup();
});
test("proxy clients receive separate request-code buckets and blocked requests do no work", async () => {
  const x = ip(),
    y = ip(),
    email = await data.address();
  data.track("ip", x);
  data.track("ip", y);
  for (let n = 0; n < 3; n++) await allowed(await post(a, x, email));
  for (let n = 0; n < 2; n++) await allowed(await post(a, y));
  await blocked(await post(a, x, email));
  expect(await data.codes(email)).toBe(3);
  await allowed(await post(a, y));
  await blocked(await post(a, y));
});
test("only the trusted suffix determines the client, including non-IP spoofed prefixes", async () => {
  const x = ip(),
    y = ip();
  data.track("ip", x);
  data.track("ip", y);
  const warnings = a.logs().split("fallback").length;
  for (const prefix of [ip(), "evil", ip()]) await allowed(await post(a, `${prefix}, ${x}`));
  await blocked(await post(a, `${ip()}, ${x}`));
  await allowed(await post(a, `evil, ${y}`));
  expect(a.logs().split("fallback").length).toBe(warnings);
  const s = await variant("2"),
    z = ip();
  data.track("ip", z);
  for (let n = 0; n < 3; n++) await allowed(await post(s, `${ip()}, ${z}, ${ip()}`));
  await blocked(await post(s, `${ip()}, ${z}, ${ip()}`));
});
test("valid JWT player identity spans replicas, token changes and shared IPs", async () => {
  const x = ip(),
    p = crypto.randomUUID(),
    q = crypto.randomUUID();
  const pk = data.track("player", p, "/api/activities");
  data.track("player", q, "/api/activities");
  const peer = data.track("ip", x, "/api/activities");
  for (let n = 0; n < 10; n++) {
    const s = n % 2 ? a : b;
    await allowed(
      await s.request("/api/activities?player_id=forged", {
        ...headers(n % 2 ? x : ip()),
        Authorization: await bearer(p),
      }),
      { activities: [] },
    );
    if (n < 9)
      await allowed(
        await s.request("/api/activities", { ...headers(x), Authorization: await bearer(q) }),
        { activities: [] },
      );
  }
  await blocked(await b.request("/api/activities", { Authorization: await bearer(p) }));
  await allowed(
    await a.request("/api/activities", { ...headers(x), Authorization: await bearer(q) }),
    { activities: [] },
  );
  await blocked(await b.request("/api/activities", { Authorization: await bearer(q) }));
  expect(await Bun.redis.get(pk)).toBe("11");
  expect(await Bun.redis.get(peer)).toBeNull();
});
test("unset trust, malformed and short trusted suffixes use the peer and warn", async () => {
  const peer = data.track("ip", "127.0.0.1");
  for (const hops of [undefined, "1", "2"]) {
    await Bun.redis.del(peer);
    const s = await variant(hops);
    const inputs =
      hops === "1" ? ["203.0.113.9, unknown", "203.0.113.9, ", undefined] : [ip(), ip(), ip()];
    for (const value of inputs) await allowed(await post(s, value));
    await blocked(await post(s, hops === undefined ? ip() : undefined));
    expect(await Bun.redis.get(peer)).toBe("4");
    if (hops) expect(s.logs()).toContain("fallback: short");
    if (hops === "1") expect(s.logs()).toContain("fallback: malformed");
  }
  await Bun.redis.del(peer);
  const v6 = "2001:db8::123";
  const k = data.track("ip", v6);
  await allowed(await post(a, `  ${v6}  `));
  expect(await Bun.redis.get(k)).toBe("1");
});
test("invalid credentials share the resolved client bucket; assets and OPTIONS follow the same rule", async () => {
  const x = ip(),
    p = crypto.randomUUID(),
    path = "/api/activities";
  const k = data.track("ip", x, path);
  data.track("player", p, path);
  const invalid = [
    undefined,
    "Bearer malformed",
    await bearer(p, undefined, true),
    (await bearer(p)).slice(0, -8) + "invalid!",
  ];
  for (let n = 0; n < 10; n++)
    expect(
      (
        await a.request(path, {
          ...headers(`${ip()}, ${x}`),
          ...(invalid[n % 4] ? { Authorization: invalid[n % 4]! } : {}),
        })
      ).status,
    ).toBe(401);
  await blocked(await b.request(path, headers(x)));
  await allowed(await a.request(path, { ...headers(x), Authorization: await bearer(p) }), {
    activities: [],
  });
  expect(await Bun.redis.get(k)).toBe("11");
  const asset = "/api/audio/missing-rate-limit.mp3";
  for (const client of [ip(), ip()]) {
    const ak = data.track("ip", client, asset);
    expect((await a.request(asset, headers(client), undefined, "OPTIONS")).status).toBe(204);
    expect(await Bun.redis.get(ak)).toBeNull();
    await a.request(asset, headers(client));
    expect(await Bun.redis.get(ak)).toBe("1");
  }
});
test("atomic concurrent first hits have a fixed bounded window, independent paths and real expiry", async () => {
  const p = crypto.randomUUID(),
    Authorization = await bearer(p),
    path = "/api/activities";
  const k = data.track("player", p, path);
  const responses = await Promise.all(
    Array.from({ length: 16 }, (_, n) => (n % 2 ? a : b).request(path, { Authorization })),
  );
  expect(responses.filter((r) => r.status === 200)).toHaveLength(10);
  expect(responses.filter((r) => r.status === 429)).toHaveLength(6);
  expect(await Bun.redis.get(k)).toBe("16");
  const ttl = async () => Number(await Bun.redis.send("PTTL", [k]));
  const first = await ttl();
  expect(first).toBeWithin(1, 60001);
  await Bun.sleep(80);
  await blocked(await a.request(path, { Authorization }));
  expect(await ttl()).toBeLessThan(first - 50);
  const other = `/rate-limit-${crypto.randomUUID()}`;
  data.track("player", p, other);
  for (let n = 0; n < 30; n++) expect((await a.request(other, { Authorization })).status).toBe(404);
  await blocked(await b.request(other, { Authorization }));
  await Bun.redis.send("PEXPIRE", [k, "40"]);
  const deadline = Date.now() + 2000;
  while ((await Bun.redis.get(k)) !== null && Date.now() < deadline) await Bun.sleep(10);
  expect(await Bun.redis.get(k)).toBeNull();
  await allowed(await b.request(path, { Authorization }), { activities: [] });
  expect(await Bun.redis.get(k)).toBe("1");
  expect(await ttl()).toBeWithin(59000, 60001);
});
test("development bypass permits more than the limit without storage", async () => {
  const s = await variant("1", "1"),
    x = ip(),
    k = data.track("ip", x);
  for (let n = 0; n < 4; n++) await allowed(await post(s, x));
  expect(await Bun.redis.get(k)).toBeNull();
});
