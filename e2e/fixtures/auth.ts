import { test as base, type Page } from "@playwright/test";
import pg from "pg";

const { Client } = pg;

interface TestUser {
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

      // Request auth code via API
      const reqRes = await fetch(
        "http://localhost:3001/api/auth/request-code",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        },
      );
      if (!reqRes.ok) {
        throw new Error(
          `request-code failed: ${reqRes.status} ${await reqRes.text()}`,
        );
      }

      // Get code directly from DB
      const codes = await queryDb<{ code: string }>(
        `SELECT code FROM auth_codes
         WHERE account_id = (SELECT id FROM accounts WHERE email = $1)
           AND used = FALSE
         ORDER BY id DESC LIMIT 1`,
        [email],
      );
      if (codes.length === 0) {
        throw new Error("No auth code found in DB");
      }
      const code = codes[0].code;

      // Verify code via API
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
          `DELETE FROM players WHERE account_id = (SELECT id FROM accounts WHERE email = $1)`,
          [email],
        );
        await queryDb(
          `DELETE FROM auth_codes WHERE account_id = (SELECT id FROM accounts WHERE email = $1)`,
          [email],
        );
        await queryDb(`DELETE FROM accounts WHERE email = $1`, [email]);
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
