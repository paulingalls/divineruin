import { test as base, type Page } from "@playwright/test";
import pg from "pg";

const { Client } = pg;

export interface TestUser {
  email: string;
  token: string;
  accountId: string;
  playerId: string;
}

function getDbUrl(): string {
  return (
    process.env.DATABASE_URL ??
    "postgresql://divineruin:divineruin@localhost:5432/divineruin"
  );
}

async function queryDb<T extends Record<string, unknown>>(
  query: string,
  params: unknown[] = [],
): Promise<T[]> {
  const client = new Client({ connectionString: getDbUrl() });
  await client.connect();
  try {
    const result = await client.query(query, params);
    return result.rows as T[];
  } finally {
    await client.end();
  }
}

export const test = base.extend<
  { authenticatedPage: Page },
  { testUser: TestUser }
>({
  testUser: [
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      const email = `e2e-${crypto.randomUUID()}@test.divineruin.com`;

      // Create account and auth code directly in DB to avoid rate limits
      await queryDb(`INSERT INTO accounts (email) VALUES ($1)`, [email]);
      const accounts = await queryDb<{ id: string }>(
        `SELECT id FROM accounts WHERE email = $1`,
        [email],
      );
      if (accounts.length === 0) throw new Error("Failed to create account");
      const accountId = accounts[0].id;

      const code = String(Math.floor(Math.random() * 1_000_000)).padStart(
        6,
        "0",
      );
      const expiresAt = new Date(Date.now() + 10 * 60_000);
      await queryDb(
        `INSERT INTO auth_codes (account_id, code, expires_at) VALUES ($1, $2, $3)`,
        [accountId, code, expiresAt.toISOString()],
      );

      // Verify code via API to get a valid JWT
      const verifyRes = await fetch(
        "http://localhost:3001/api/auth/verify-code",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, code }),
        },
      );
      if (!verifyRes.ok) {
        throw new Error(
          `verify-code failed: ${verifyRes.status} ${await verifyRes.text()}`,
        );
      }

      const data = (await verifyRes.json()) as {
        token: string;
        account_id: string;
        player_id: string;
      };

      const testUser: TestUser = {
        email,
        token: data.token,
        accountId: data.account_id,
        playerId: data.player_id,
      };

      await use(testUser);

      // Teardown: clean up test user data
      try {
        await queryDb(
          `DELETE FROM async_activities WHERE player_id IN (SELECT player_id FROM players WHERE account_id = $1)`,
          [accountId],
        );
        await queryDb(`DELETE FROM players WHERE account_id = $1`, [accountId]);
        await queryDb(`DELETE FROM auth_codes WHERE account_id = $1`, [
          accountId,
        ]);
        await queryDb(`DELETE FROM accounts WHERE id = $1`, [accountId]);
      } catch (e) {
        console.warn("Teardown cleanup failed:", e);
      }
    },
    { scope: "worker" },
  ],

  authenticatedPage: async ({ page, testUser }, use) => {
    // Navigate to base URL to establish origin for localStorage
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    // Inject auth credentials into localStorage
    await page.evaluate(
      ({ token, accountId, playerId, email }) => {
        localStorage.setItem("auth_token", token);
        localStorage.setItem("account_id", accountId);
        localStorage.setItem("player_id", playerId);
        localStorage.setItem("account_email", email);
      },
      {
        token: testUser.token,
        accountId: testUser.accountId,
        playerId: testUser.playerId,
        email: testUser.email,
      },
    );

    // Reload so the app reads from localStorage
    await page.reload();
    await page.waitForLoadState("domcontentloaded");

    await use(page);
  },
});

export { expect } from "@playwright/test";
export { queryDb };
