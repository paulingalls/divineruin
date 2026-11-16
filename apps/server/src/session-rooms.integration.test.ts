import { afterAll, beforeAll, beforeEach, expect, test } from "bun:test";
import { TokenVerifier } from "livekit-server-sdk";
import {
  gate,
  installSeam,
  Recording,
  request,
  type Message,
  type Result,
} from "./session-room-process.fixture.ts";

if (!process.env.REDIS_URL) throw new Error("session rooms require REDIS_URL");
const recording = new Recording();
const players: string[] = [];
const rooms: string[] = [];
const codes: string[] = [];
function id(list: string[]) {
  const value = `test_${crypto.randomUUID()}`;
  list.push(value);
  return value;
}
const player = () => id(players);
const room = () => id(rooms);
const token = (p: string, r: string) => request(p, "token", { room_name: r, player_id: "forged" });
async function jwt(result: Result, p: string, r: string) {
  expect(result.status).toBe(200);
  const claims = await new TokenVerifier(
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!,
  ).verify(String(result.body.token));
  expect(claims.sub).toBe(p);
  expect(claims.video?.room).toBe(r);
  expect(claims.video?.roomJoin).toBe(true);
}
async function owned(p: string, r: string) {
  expect(await Bun.redis.get(`player_room:${p}`)).toBe(r);
  expect(await Bun.redis.get(`room_owner:${r}`)).toBe(p);
  expect(await Bun.redis.get(`room_dispatched:${r}`)).toBe(p);
}
async function empty(p: string, r: string) {
  expect(await Bun.redis.get(`player_room:${p}`)).toBeNull();
  expect(await Bun.redis.get(`room_owner:${r}`)).toBeNull();
  expect(await Bun.redis.get(`room_dispatched:${r}`)).toBeNull();
}
const children: ReturnType<typeof Bun.spawn>[] = [];
const entered = new Map<string, () => void>();
const responses = new Map<string, (result: Result) => void>();
async function child() {
  const ready = gate();
  const proc = Bun.spawn([process.execPath, `${import.meta.dir}/session-room-process.fixture.ts`], {
    env: process.env,
    stdout: "ignore",
    stderr: "inherit",
    ipc(message: Message, subprocess) {
      if (message.kind === "ready") ready.release();
      if (message.kind === "entered") {
        entered.get(message.id)!();
        entered.delete(message.id);
      }
      if (message.kind === "result") {
        responses.get(message.id)!(message.result!);
        responses.delete(message.id);
      }
      if (message.kind === "call")
        void recording.invoke(message.call!).then(
          () => subprocess.send({ kind: "reply", id: message.id } satisfies Message),
          (error: Error) =>
            subprocess.send({
              kind: "reply",
              id: message.id,
              error: error.message,
            } satisfies Message),
        );
    },
  });
  children.push(proc);
  await Promise.race([
    ready.promise,
    Bun.sleep(5000).then(() => {
      throw new Error("child readiness deadline");
    }),
  ]);
  return (p: string, r: string) => {
    const started = gate();
    const result = new Promise<Result>((resolve, reject) => {
      const id = crypto.randomUUID();
      const timeout = setTimeout(() => reject(new Error("child request deadline")), 15000);
      entered.set(id, started.release);
      responses.set(id, (result) => {
        clearTimeout(timeout);
        resolve(result);
      });
      proc.send({
        kind: "request",
        id,
        player: p,
        path: "token",
        body: { room_name: r },
      } satisfies Message);
    });
    return Object.assign(result, { entered: started.promise });
  };
}
let first: Awaited<ReturnType<typeof child>>;
let second: typeof first;
beforeAll(async () => {
  await Bun.redis.ping();
  await installSeam((call) => recording.invoke(call));
  first = await child();
  second = await child();
});
beforeEach(() => recording.reset());
afterAll(async () => {
  recording.pause?.resume.release();
  for (const proc of children) {
    proc.kill();
    await proc.exited;
  }
  const keys = [
    ...players.flatMap((p) => [`player_room:${p}`, `session_lock:player:${p}`]),
    ...rooms.flatMap((r) => [`room_owner:${r}`, `room_dispatched:${r}`, `session_lock:room:${r}`]),
    ...codes.map((c) => `invite:${c}`),
  ];
  if (keys.length) await Bun.redis.del(...keys);
  Bun.redis.close();
});

test("takeover deletes the old room before create/dispatch and aligns finite ownership TTLs", async () => {
  const p = player(),
    a = room(),
    b = room();
  await jwt(await token(p, a), p, a);
  await jwt(await token(p, b), p, b);
  expect(recording.calls.map((c) => [c.operation, c.room])).toEqual([
    ["create", a],
    ["dispatch", a],
    ["delete", a],
    ["create", b],
    ["dispatch", b],
  ]);
  await owned(p, b);
  expect(await Bun.redis.get(`room_owner:${a}`)).toBeNull();
  expect(await Bun.redis.get(`room_dispatched:${a}`)).toBeNull();
  const ttls = await Promise.all(
    [`player_room:${p}`, `room_owner:${b}`, `room_dispatched:${b}`].map((key) =>
      Bun.redis.send("TTL", [key]),
    ),
  );
  for (const ttl of ttls) expect(Number(ttl)).toBeGreaterThan(3600);
  expect(new Set(ttls).size).toBe(1);
  expect([...recording.live]).toEqual([b]);
});

test("same-room sequential, overlapping and two-process requests dispatch once", async () => {
  const p = player(),
    r = room();
  const hold = recording.hold("dispatch", r);
  const one = first(p, r);
  await hold.entered.promise;
  const two = second(p, r);
  const local = [token(p, r), token(p, r)];
  await two.entered;
  hold.resume.release();
  const results = await Promise.all([one, two, ...local]);
  results.push(await token(p, r));
  for (const result of results) await jwt(result, p, r);
  expect(recording.calls.map((c) => c.operation)).toEqual(["create", "dispatch"]);
  await owned(p, r);
});

test("stranded ownership without a dispatched marker recovers instead of issuing an empty-room token", async () => {
  const p = player(),
    r = room();
  await Bun.redis.send("MSET", [`player_room:${p}`, r, `room_owner:${r}`, p]);
  expect((await request(p, "invite", { room_name: r })).status).toBe(403);
  await jwt(await token(p, r), p, r);
  expect(recording.calls.map((c) => c.operation)).toEqual(["create", "dispatch"]);
  await owned(p, r);
});

test("two processes serialize different rooms while unrelated transitions progress", async () => {
  const p = player(),
    a = room(),
    b = room(),
    q = player(),
    c = room();
  const hold = recording.hold("dispatch", a);
  const one = first(p, a);
  await hold.entered.promise;
  const two = second(p, b);
  await two.entered;
  await jwt(await token(q, c), q, c);
  hold.resume.release();
  await jwt(await one, p, a);
  await jwt(await two, p, b);
  await owned(p, b);
  expect(
    recording.calls.filter((call) => call.room !== c).map((call) => [call.operation, call.room]),
  ).toEqual([
    ["create", a],
    ["dispatch", a],
    ["delete", a],
    ["create", b],
    ["dispatch", b],
  ]);
  expect([...recording.live].sort()).toEqual([b, c].sort());
});

test("two players racing for one room give only its owner a token and dispatch", async () => {
  const p = player(),
    q = player(),
    r = room();
  const results = await Promise.all([first(p, r), second(q, r)]);
  expect(results.map((x) => x.status).sort()).toEqual([200, 403]);
  const winner = results[0].status === 200 ? p : q;
  await jwt(
    results.find((x) => x.status === 200)!,
    winner,
    r,
  );
  await owned(winner, r);
  expect(recording.calls).toEqual([
    { operation: "create", room: r },
    { operation: "dispatch", room: r, player: winner },
  ]);
});

for (const takeover of [false, true])
  test(`create failure rolls back without dispatch; takeover=${takeover}`, async () => {
    const p = player(),
      a = room(),
      b = room();
    if (takeover) await jwt(await token(p, a), p, a);
    recording.failure = "create";
    const result = await token(p, b);
    expect(result.status).toBe(503);
    expect(result.body.error).toBeString();
    expect(result.body.token).toBeUndefined();
    await empty(p, b);
    expect(recording.calls.filter((c) => c.operation === "dispatch")).toHaveLength(
      takeover ? 1 : 0,
    );
    if (takeover) expect(await Bun.redis.get(`room_owner:${a}`)).toBeNull();
    recording.failure = undefined;
    await jwt(await token(p, b), p, b);
  });

test("old-room delete failure retains ownership and prevents another room; retry succeeds", async () => {
  const p = player(),
    a = room(),
    b = room();
  await token(p, a);
  recording.failure = "delete";
  const result = await token(p, b);
  expect(result.status).toBe(503);
  expect(result.body.token).toBeUndefined();
  await owned(p, a);
  expect(recording.calls.map((c) => c.operation)).toEqual(["create", "dispatch", "delete"]);
  recording.failure = undefined;
  await jwt(await token(p, b), p, b);
});

test("real SDK not_found on an already-ended old room permits takeover", async () => {
  const p = player(),
    a = room(),
    b = room();
  await token(p, a);
  recording.live.delete(a);
  recording.failure = "delete";
  recording.absent = true;
  await jwt(await token(p, b), p, b);
  await owned(p, b);
  expect([...recording.live]).toEqual([b]);
});

test("lost transition authority cannot dispatch, mint, roll back or delete successor ownership", async () => {
  const p = player(),
    r = room();
  const hold = recording.hold("create", r);
  const pending = token(p, r);
  await hold.entered.promise;
  await Bun.redis.send("MSET", [
    `session_lock:player:${p}`,
    "successor",
    `session_lock:room:${r}`,
    "successor",
    `player_room:${p}`,
    r,
    `room_owner:${r}`,
    p,
    `room_dispatched:${r}`,
    p,
  ]);
  hold.resume.release();
  const result = await pending;
  expect(result.status).toBe(503);
  expect(result.body.token).toBeUndefined();
  await owned(p, r);
  expect(await Bun.redis.get(`session_lock:player:${p}`)).toBe("successor");
  expect(recording.calls.map((c) => c.operation)).toEqual(["create"]);
});

test("foreign token and invites are refused without changing either player's live room", async () => {
  const p = player(),
    q = player(),
    r = room(),
    s = room();
  await token(p, r);
  await token(q, s);
  const before = [...recording.calls];
  expect((await token(q, r)).status).toBe(403);
  expect((await request(q, "invite", { room_name: r })).status).toBe(403);
  expect((await request(q, "invite", { room_name: room() })).status).toBe(403);
  expect(recording.calls).toEqual(before);
  await owned(p, r);
  await owned(q, s);
});

test("owner invite/redeem preserves authenticated JWT identities and ignores forged fields", async () => {
  const p = player(),
    q = player(),
    r = room();
  await jwt(await token(p, r), p, r);
  const invite = await request(p, "invite", { room_name: r, player_id: q });
  expect(invite.status).toBe(200);
  expect(Number(invite.body.expires_in)).toBeGreaterThan(0);
  const code = String(invite.body.code);
  codes.push(code);
  await jwt(await request(q, "redeem", { code, room_name: "forged", player_id: p }), q, r);
  await owned(p, r);
  expect(await Bun.redis.get(`player_room:${q}`)).toBeNull();
  expect(recording.calls.map((c) => c.operation)).toEqual(["create", "dispatch"]);
  expect((await request(q, "redeem", { code: "unknown" })).status).toBe(404);
  await Bun.redis.del(`invite:${code}`);
  const expired = await request(q, "redeem", { code });
  expect(expired.status).toBe(404);
  expect(expired.body.token).toBeUndefined();
});

test("dispatch failure returns the exact 503, deletes room and keys, then allows fresh retry", async () => {
  const p = player(),
    r = room(),
    s = room();
  recording.failure = "dispatch";
  const result = await token(p, r);
  expect(result).toEqual({ status: 503, body: { error: "The DM could not join. Try again." } });
  expect(recording.calls.map((c) => c.operation)).toEqual(["create", "dispatch", "delete"]);
  await empty(p, r);
  expect(recording.live.size).toBe(0);
  recording.failure = undefined;
  await jwt(await token(p, s), p, s);
});
