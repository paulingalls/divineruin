import { afterAll, beforeAll, describe, expect, mock, test } from "bun:test";
import { assertDbRequired } from "@divineruin/shared/test-util";
import { resolve } from "node:path";
import { sql } from "./db.ts";

const previous = {
  PORT: process.env.PORT,
  SERVER_HOST: process.env.SERVER_HOST,
  JWT_SECRET: process.env.JWT_SECRET,
  RATE_LIMIT_BYPASS: process.env.RATE_LIMIT_BYPASS,
};
process.env.JWT_SECRET = "ab".repeat(32);
process.env.RATE_LIMIT_BYPASS = "1";
const sends: { email: string; code: string; minutes: number }[] = [];
void mock.module("./email-transport.ts", () => ({
  sendVerificationEmail: (email: string, code: string, minutes: number) => {
    sends.push({ email, code, minutes });
    return Promise.resolve();
  },
}));
const { startServer } = await import("./index.ts");
const { verifyJwt } = await import("./auth.ts");
const hasDb = Boolean(process.env.DATABASE_URL);
test("required signin database is available", () => assertDbRequired(hasDb));

describe.skipIf(!hasDb)("invite-only sign-in through HTTP and operator CLI", () => {
  let server: Awaited<ReturnType<typeof startServer>>;
  const emails: string[] = [];
  function address() {
    const email = `friend-${crypto.randomUUID()}@mail.example.com`;
    emails.push(email);
    return email;
  }
  async function cli(...args: string[]) {
    const child = Bun.spawn([process.execPath, "run", "allow", ...args], {
      cwd: resolve(import.meta.dir, "../../.."),
      env: process.env,
      stdout: "pipe",
      stderr: "pipe",
    });
    const [status, stderr] = await Promise.all([
      child.exited,
      new Response(child.stderr).text(),
      new Response(child.stdout).text(),
    ]);
    return { status, stderr };
  }
  async function allow(email: string) {
    const result = await cli(` ${email.toUpperCase()} `);
    expect(result, result.stderr).toMatchObject({ status: 0 });
  }
  async function post(path: string, email: string, code?: string) {
    return fetch(new URL(`/api/auth/${path}`, server.url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code }),
    });
  }
  async function login(email: string) {
    expect((await post("request-code", ` ${email.toUpperCase()} `)).status).toBe(200);
    const send = sends.at(-1)!;
    expect(send).toMatchObject({ email, minutes: 10 });
    expect(send.code).toMatch(/^\d{6}$/);
    const response = await post("verify-code", ` ${email.toUpperCase()} `, send.code);
    expect(response.status).toBe(200);
    const auth = (await response.json()) as {
      token: string;
      account_id: string;
      player_id: string;
    };
    expect(await verifyJwt(auth.token)).toEqual({
      accountId: auth.account_id,
      playerId: auth.player_id,
    });
    return auth;
  }
  beforeAll(async () => {
    process.env.PORT = "0";
    process.env.SERVER_HOST = "127.0.0.1";
    server = await startServer();
  });
  afterAll(async () => {
    try {
      for (const email of emails) {
        await sql`DELETE FROM players WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await sql`DELETE FROM auth_codes WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await sql`DELETE FROM accounts WHERE email=${email}`;
        await sql`DELETE FROM signin_allowlist WHERE email=${email}`;
      }
    } finally {
      await server.stop(true);
      mock.restore();
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
    }
  });
  test("CLI adds one normalized membership and both first and returning sign-in succeed", async () => {
    const email = address();
    await allow(email);
    await allow(email);
    const rows = await sql<
      { email: string; added_at: Date }[]
    >`SELECT email, added_at FROM signin_allowlist WHERE email=${email}`;
    expect(rows).toHaveLength(1);
    expect(rows[0]!.added_at).toBeTruthy();
    const before = sends.length;
    const first = await login(email);
    const returning = await login(email);
    expect(returning.player_id).toBe(first.player_id);
    expect(sends.length - before).toBe(2);
    expect(await sql`SELECT id FROM accounts WHERE email=${email}`).toEqual([
      { id: first.account_id },
    ]);
    expect(await sql`SELECT player_id FROM players WHERE account_id=${first.account_id}`).toEqual([
      { player_id: first.player_id },
    ]);
  });
  test("unlisted request returns the invitation message without account or email", async () => {
    const email = address();
    const before = sends.length;
    const response = await post("request-code", ` ${email.toUpperCase()} `);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "This playtest is invite-only" });
    expect(await sql`SELECT id FROM accounts WHERE email=${email}`).toHaveLength(0);
    expect(sends.length).toBe(before);
  });
  test("removing membership denies a fresh valid code and future requests", async () => {
    const email = address();
    await allow(email);
    const auth = await login(email);
    expect((await post("request-code", email)).status).toBe(200);
    const code = sends.at(-1)!.code;
    const active = await sql<
      { id: string }[]
    >`SELECT id FROM auth_codes WHERE account_id=${auth.account_id} AND code=${code} AND used=false AND expires_at>now()`;
    expect(active).toHaveLength(1);
    for (let i = 0; i < 2; i++) {
      const result = await cli("--remove", ` ${email.toUpperCase()} `);
      expect(result, result.stderr).toMatchObject({ status: 0 });
    }
    expect(await sql`SELECT email FROM signin_allowlist WHERE email=${email}`).toHaveLength(0);
    expect(await sql`SELECT id FROM accounts WHERE email=${email}`).toHaveLength(1);
    const response = await post("verify-code", email, code);
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "This playtest is invite-only" });
    expect(
      await sql`SELECT id FROM auth_codes WHERE id=${active[0]!.id} AND used=false`,
    ).toHaveLength(1);
    const before = sends.length;
    const codes = await sql<
      { id: string }[]
    >`SELECT id FROM auth_codes WHERE account_id=${auth.account_id} ORDER BY id`;
    expect((await post("request-code", email)).status).toBe(403);
    expect(sends.length).toBe(before);
    expect(
      await sql<
        { id: string }[]
      >`SELECT id FROM auth_codes WHERE account_id=${auth.account_id} ORDER BY id`,
    ).toEqual(codes);
  });
  test("invalid CLI input and argument shapes fail without writes", async () => {
    const email = address();
    for (const args of [[], ["invalid"], ["--remove"], [email, "extra"], ["--other", email]]) {
      expect((await cli(...args)).status).not.toBe(0);
    }
    expect(await sql`SELECT email FROM signin_allowlist WHERE email=${email}`).toHaveLength(0);
    expect(await sql`SELECT id FROM accounts WHERE email=${email}`).toHaveLength(0);
  });
});
