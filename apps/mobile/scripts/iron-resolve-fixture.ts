import { SQL } from "bun";

export async function withCharacterFixture(
  api: string,
  databaseUrl: string | undefined,
  run: (route: string) => Promise<void>,
): Promise<void> {
  if (!databaseUrl) throw new Error("Native temp HP fixture requires DATABASE_URL");
  const sql = new SQL(databaseUrl);
  const email = `native-temp-hp-${crypto.randomUUID()}@example.com`;
  try {
    await sql`INSERT INTO signin_allowlist(email) VALUES(${email})`;
    const accounts = await sql<
      { id: string }[]
    >`INSERT INTO accounts(email) VALUES(${email}) RETURNING id`;
    const account = accounts.at(0);
    if (!account) throw new Error("Native temp HP fixture account was not created");
    await sql`INSERT INTO auth_codes(account_id,code,expires_at) VALUES(${account.id},'123456',now()+interval '10 minutes')`;
    const response = await fetch(`${api}/api/auth/verify-code`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code: "123456" }),
    });
    if (!response.ok) throw new Error(`Native fixture auth failed: ${response.status}`);
    const auth = (await response.json()) as {
      token: string;
      account_id: string;
      player_id: string;
    };
    await sql`UPDATE players SET data=${{
      name: "Kael",
      class: "warrior",
      hp: { current: 12, max: 20 },
      temp_hp: 7,
    }} WHERE account_id=${account.id} AND player_id=${auth.player_id}`;
    const fixture = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch: (req) =>
        new URL(req.url).pathname === "/fixture" && req.method === "GET"
          ? Response.json(auth)
          : new Response(null, { status: 404 }),
    });
    try {
      const origin = `http://127.0.0.1:${fixture.port}`;
      await run(`divineruin://iron-resolve-test?fixture=${encodeURIComponent(origin)}`);
    } finally {
      await fixture.stop(true);
    }
  } finally {
    try {
      await sql.begin(async (transaction) => {
        await transaction`DELETE FROM players WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await transaction`DELETE FROM auth_codes WHERE account_id IN (SELECT id FROM accounts WHERE email=${email})`;
        await transaction`DELETE FROM accounts WHERE email=${email}`;
        await transaction`DELETE FROM signin_allowlist WHERE email=${email}`;
      });
    } finally {
      await sql.close();
    }
  }
}
