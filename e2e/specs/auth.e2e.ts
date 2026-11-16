import { test, expect, queryDb, cleanupAccountByEmail } from "../fixtures/auth.js";

test.describe("Auth flow", () => {
  test("uninvited email shows the server invitation message", async ({ page }) => {
    const email = `uninvited-${crypto.randomUUID()}@test.divineruin.com`;
    try {
      await page.goto("/");
      await page.getByPlaceholder("adventurer@example.com").fill(email);
      const response = page.waitForResponse(
        (r) => r.url().endsWith("/api/auth/request-code") && r.request().method() === "POST",
      );
      await page.getByText("SEND CODE", { exact: true }).click();
      expect((await response).status()).toBe(403);
      await expect(page.getByText("This playtest is invite-only", { exact: true })).toBeVisible();
      await expect(page.getByPlaceholder("adventurer@example.com")).toBeVisible();
      await expect(page.getByPlaceholder("000000")).toHaveCount(0);
    } finally {
      await cleanupAccountByEmail(email);
    }
  });
  test("full sign-in via email code", async ({ page }) => {
    const email = `e2e-auth-${crypto.randomUUID()}@test.divineruin.com`;

    try {
      await queryDb("INSERT INTO signin_allowlist(email) VALUES($1)", [email]);
      // Navigate to auth screen
      await page.goto("/");
      await page.waitForLoadState("domcontentloaded");

      // Assert we're on the auth screen
      await expect(page.getByText("Listen to the dark")).toBeVisible();

      // Fill email
      const emailInput = page.getByPlaceholder("adventurer@example.com");
      await expect(emailInput).toBeVisible();
      await emailInput.fill(email);

      // Click send code
      await page.getByText("SEND CODE", { exact: true }).click();

      // Wait for code input to appear
      const codeInput = page.getByPlaceholder("000000");
      await expect(codeInput).toBeVisible();

      // Get verification code from DB
      const codes = await queryDb<{ code: string }>(
        `SELECT code FROM auth_codes
       WHERE account_id = (SELECT id FROM accounts WHERE email = $1)
         AND used = FALSE
       ORDER BY id DESC LIMIT 1`,
        [email],
      );
      expect(codes.length).toBeGreaterThan(0);
      const code = codes[0].code;

      // Fill code and verify
      await codeInput.fill(code);
      await page.getByText("VERIFY", { exact: true }).click();

      // Assert redirect to home screen
      await expect(page.getByText("Your story is about to begin.")).toBeVisible();
    } finally {
      await cleanupAccountByEmail(email);
    }
  });
});
