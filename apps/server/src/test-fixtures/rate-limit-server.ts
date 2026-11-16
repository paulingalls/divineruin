import { mock } from "bun:test";
import { sql } from "../db.ts";

export const secret = "ab".repeat(32);
export const codePath = "/api/auth/request-code";
export const key = (kind: string, id: string, path = codePath) =>
  `rate-limit:${JSON.stringify([kind, id, path])}`;
export function spawnServer(
  overrides: Record<string, string | undefined> = {},
  entry = import.meta.path,
) {
  return Bun.spawn([process.execPath, "--no-env-file", entry], {
    env: {
      ...process.env,
      NODE_ENV: "development",
      JWT_SECRET: secret,
      PORT: "0",
      SERVER_HOST: "127.0.0.1",
      EMAIL_TRANSPORT: "mock",
      BUN_TEST: undefined,
      RATE_LIMIT_BYPASS: undefined,
      TRUSTED_PROXY_HOPS: "1",
      ...overrides,
    },
    stdout: "pipe",
    stderr: "pipe",
  });
}
export async function launch(overrides: Record<string, string | undefined> = {}) {
  const proc = spawnServer(overrides);
  let logs = "";
  async function drain(stream: ReadableStream<Uint8Array>) {
    for await (const bytes of stream) logs += new TextDecoder().decode(bytes);
  }
  const drains = Promise.all([drain(proc.stdout), drain(proc.stderr)]);
  const deadline = Date.now() + 10000;
  while (!logs.includes("Server running at ")) {
    if (proc.exitCode !== null || Date.now() > deadline) {
      proc.kill();
      await drains;
      throw new Error(`Server failed readiness: ${logs}`);
    }
    await Bun.sleep(10);
  }
  const url = logs.match(/Server running at (http:\/\/\S+)/)![1]!;
  return {
    proc,
    logs: () => logs,
    request: (
      path: string,
      headers: Record<string, string> = {},
      body?: unknown,
      method?: string,
    ) =>
      fetch(new URL(path, url), {
        method: method ?? (body ? "POST" : "GET"),
        headers: { "Content-Type": "application/json", ...headers },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(10000),
      }),
    async stop() {
      proc.kill();
      await Promise.race([
        Promise.all([proc.exited, drains]),
        Bun.sleep(3000).then(() => {
          proc.kill("SIGKILL");
          throw new Error("Server shutdown timed out");
        }),
      ]);
    },
  };
}
export async function resources() {
  if (!process.env.DATABASE_URL || !process.env.REDIS_URL)
    throw new Error("Real DB and Valkey required");
  await sql`SELECT 1`;
  if ((await Bun.redis.send("PING", [])) !== "PONG") throw new Error("Valkey unavailable");
  const keys = new Set<string>();
  const emails: string[] = [];
  return {
    track(kind: string, id: string, path = codePath) {
      const k = key(kind, id, path);
      keys.add(k);
      return k;
    },
    async address() {
      const email = `rate-${crypto.randomUUID()}@mail.example.com`;
      emails.push(email);
      await sql`INSERT INTO signin_allowlist (email) VALUES (${email})`;
      return email;
    },
    async codes(email: string) {
      const rows = await sql<
        { id: string }[]
      >`SELECT c.id FROM auth_codes c JOIN accounts a ON a.id=c.account_id WHERE a.email=${email}`;
      return rows.length;
    },
    async cleanup() {
      for (const k of keys) await Bun.redis.del(k);
      for (const email of emails) {
        await sql`DELETE FROM auth_codes WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await sql`DELETE FROM accounts WHERE email=${email}`;
        await sql`DELETE FROM signin_allowlist WHERE email=${email}`;
      }
    },
  };
}
if (import.meta.main) {
  void mock.module("../email-transport.ts", () => ({
    sendVerificationEmail: () => {
      console.log("rate-limit email sent");
      return Promise.resolve();
    },
  }));
  const { startServer } = await import("../index.ts");
  await startServer();
}
