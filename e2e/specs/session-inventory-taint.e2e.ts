import { test, expect, queryDb } from "../fixtures/character.js";

test.use({ viewport: { width: 390, height: 844 } });

test("clean and tainted rend shards have separate HUD rows and quantities", async ({
  page,
  testUser,
  testCharacter: _,
}) => {
  await queryDb("DELETE FROM player_inventory WHERE player_id = $1", [testUser.playerId]);
  await queryDb(
    `INSERT INTO player_inventory (player_id, item_id, tainted, data) VALUES
     ($1, 'rend_shard', false, '{"quantity":2}'),
     ($1, 'rend_shard', true, '{"quantity":1}')`,
    [testUser.playerId],
  );
  await page.addInitScript((user) => {
    localStorage.setItem("auth_token", user.token);
    localStorage.setItem("player_id", user.playerId);
    localStorage.setItem("account_id", user.accountId);
  }, testUser);
  await page.goto("/session-test");
  await page.waitForFunction(() => !!window.__DR);
  await page.evaluate(() => window.__DR!.openPanel("inventory"));

  const clean = page.getByLabel("Rend Shard, clean, 2", { exact: true });
  const tainted = page.getByLabel("Rend Shard, tainted, 1", { exact: true });
  await expect(clean).toBeVisible();
  await expect(tainted).toBeVisible();
  await expect(tainted.getByText("Tainted", { exact: true })).toBeVisible();

  await clean.click();
  await expect(page.getByText("Clean quantity 2", { exact: true })).toBeVisible();
  await page.getByText("← Back", { exact: true }).click();
  await tainted.click();
  await expect(page.getByText("Tainted quantity 1", { exact: true })).toBeVisible();
});
