import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { assertDbRequired } from "@divineruin/shared/test-util";
process.env.JWT_SECRET = "ab".repeat(32);
const { startServer } = await import("./index.ts");
import { sql } from "./db.ts";

type Activity = {
  id: string;
  activity_type: string;
  status: string;
  resolve_at: string;
  decision_options: { id: string }[];
};
type Snapshot = {
  inventory_revision: string;
  inventory: { id: string; tainted: boolean; slot_info: { quantity: number } }[];
};
const hasDb = Boolean(process.env.DATABASE_URL);
test("required purification database is available", () => assertDbRequired(hasDb));

describe.skipIf(!hasDb)("purification over public command, worker and HTTP", () => {
  let server: Awaited<ReturnType<typeof startServer>>;
  let pid: string;
  let accountId: string;
  let token: string;
  const oldPort = process.env.PORT;
  const oldHost = process.env.SERVER_HOST;
  const request = async (path: string, body?: unknown) => {
    const response = await fetch(new URL(path, server.url), {
      method: body ? "POST" : "GET",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    expect(response.status).toBe(200);
    return response.json();
  };
  beforeAll(async () => {
    process.env.PORT = "0";
    process.env.SERVER_HOST = "127.0.0.1";
    server = await startServer();
    const email = `purification_${crypto.randomUUID()}@example.com`;
    const [account] = await sql<
      { id: string }[]
    >`INSERT INTO accounts(email) VALUES(${email}) RETURNING id`;
    accountId = account!.id;
    await sql`INSERT INTO auth_codes(account_id,code,expires_at) VALUES(${accountId},'123456',now()+interval '10 minutes')`;
    const response = await fetch(new URL("/api/auth/verify-code", server.url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code: "123456" }),
    });
    expect(response.status).toBe(200);
    const auth = (await response.json()) as { player_id: string; token: string };
    pid = auth.player_id;
    token = auth.token;
    await sql`UPDATE players SET data=data || '{"class":"artificer","name":"Artificer","location_id":"accord_guild_hall"}'::jsonb WHERE player_id=${pid}`;
  });
  afterAll(async () => {
    if (pid) {
      await sql`DELETE FROM async_activities WHERE player_id=${pid}`;
      await sql`DELETE FROM players WHERE player_id=${pid}`;
    }
    if (accountId) {
      await sql`DELETE FROM auth_codes WHERE account_id=${accountId}`;
      await sql`DELETE FROM accounts WHERE id=${accountId}`;
    }
    await server.stop(true);
    if (oldPort === undefined) delete process.env.PORT;
    else process.env.PORT = oldPort;
    if (oldHost === undefined) delete process.env.SERVER_HOST;
    else process.env.SERVER_HOST = oldHost;
  });
  test("persisted timer is listed and worker credit precedes collection without a second grant", async () => {
    const env = { ...process.env };
    for (const key of [
      "ANTHROPIC_API_KEY",
      "OPENAI_API_KEY",
      "INWORLD_API_KEY",
      "DEEPGRAM_API_KEY",
    ])
      delete env[key];
    const child = Bun.spawn(
      [
        "uv",
        "run",
        "--no-sync",
        "--project",
        "../agent",
        "python",
        "-c",
        "import sys; sys.path[:0]=['../agent/tests','../agent']; from _paid_tests import install_paid_call_guard; install_paid_call_guard(); import asyncio; from acceptance.purification_harness import main; asyncio.run(main())",
        pid,
      ],
      { cwd: `${import.meta.dir}/..`, stdin: "pipe", stdout: "pipe", stderr: "pipe", env },
    );
    const errors = new Response(child.stderr).text();
    const reader = child.stdout.getReader();
    let pending = "";
    async function line(): Promise<string> {
      while (!pending.includes("\n")) {
        const { value, done } = await reader.read();
        if (done) throw new Error(`Python exited: ${await errors}`);
        pending += new TextDecoder().decode(value);
      }
      const index = pending.indexOf("\n");
      const output = pending.slice(0, index);
      pending = pending.slice(index + 1);
      return output;
    }
    try {
      const started = JSON.parse(await line()) as { activity_id: string; resolve_at: string };
      const detail = (await request(`/api/activities/${started.activity_id}`)) as Activity;
      expect(detail).toMatchObject({
        id: started.activity_id,
        activity_type: "purification",
        status: "in_progress",
        resolve_at: started.resolve_at,
      });
      expect(
        ((await request("/api/activities")) as { activities: Activity[] }).activities,
      ).toContainEqual(detail);
      await child.stdin.write("resolve\n");
      const worker = JSON.parse(await line()) as Activity;
      expect(worker.status).toBe("resolved");
      const resolved = (await request(`/api/activities/${started.activity_id}`)) as Activity;
      expect(resolved.status).toBe("resolved");
      expect(
        ((await request("/api/activities")) as { activities: Activity[] }).activities,
      ).toContainEqual(resolved);
      const credited = (await request("/api/inventory")) as Snapshot;
      expect(credited.inventory.map((i) => [i.id, i.tainted, i.slot_info.quantity])).toEqual([
        ["rend_shard", false, 7],
        ["rend_shard", true, 1],
      ]);
      await request(`/api/activities/${started.activity_id}/decide`, {
        decision_id: resolved.decision_options[0]!.id,
      });
      expect(((await request(`/api/activities/${started.activity_id}`)) as Activity).status).toBe(
        "collected",
      );
      expect(await request("/api/inventory")).toEqual(credited);
      await child.stdin.write("done\n");
      await child.stdin.end();
      expect(await child.exited, await errors).toBe(0);
    } finally {
      child.kill();
      await child.exited;
    }
  }, 30000);
});
