import { test, expect, queryDb } from "../fixtures/character.js";
import { API_ORIGIN } from "../ports.js";
import { type Browser, type Page } from "@playwright/test";
import { spawnSync } from "node:child_process";
import pg from "pg";
import { requireEnvironment } from "../require-environment.js";

type Snapshot = {
  player_id: string;
  inventory: {
    id: string;
    name: string;
    type: string;
    slot_info: { quantity: number; equipped?: boolean };
    image_url?: string;
  }[];
};
async function inventory(token: string, query = "") {
  const res = await fetch(`${API_ORIGIN}/api/inventory${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.status).toBe(200);
  return (await res.json()) as Snapshot;
}
const sorted = <T extends { id: string }>(items: T[]) =>
  [...items].sort((a, b) => a.id.localeCompare(b.id));
function pythonInventory(player: string) {
  const result = spawnSync(
    "uv",
    ["run", "--project", "../apps/agent", "python", "fixtures/inventory-snapshot.py", player],
    { encoding: "utf8" },
  );
  expect(result.status, result.stderr).toBe(0);
  return JSON.parse(result.stdout) as Snapshot["inventory"];
}
async function seed(player: string, other = false) {
  await queryDb("DELETE FROM player_inventory WHERE player_id = $1", [player]);
  const rows = other
    ? [["wolf_pelt", 7]]
    : [
        ["iron_ingot", 5],
        ["leather_strip", 1],
        ["crystal_flask", 2],
        ["iron_sword", 1],
        ["hollow_bone_fragment", 1],
      ];
  for (const [id, quantity] of rows)
    await queryDb("INSERT INTO player_inventory(player_id,item_id,data) VALUES($1,$2,$3::jsonb)", [
      player,
      id,
      JSON.stringify({ quantity, equipped: id === "iron_sword" }),
    ]);
  await queryDb("UPDATE players SET data = $1::jsonb WHERE player_id=$2", [
    JSON.stringify({
      name: "Craft Tester",
      class: "warrior",
      location_id: "millhaven",
      proficiencies: ["crafting"],
    }),
    player,
  ]);
  await queryDb(
    "INSERT INTO workspace_rentals(id,player_id,location_id,workspace_type,source) VALUES($2,$1,'millhaven','forge','fixture')",
    [player, `rental-${crypto.randomUUID()}`],
  );
}
async function device(
  browser: Browser,
  user: { token: string; playerId: string; accountId: string },
) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript((user) => {
    localStorage.setItem("auth_token", user.token);
    localStorage.setItem("player_id", user.playerId);
    localStorage.setItem("account_id", user.accountId);
  }, user);
  await page.goto("/session-test");
  await page.waitForFunction(() => !!window.__DR);
  await page.evaluate(() => window.__DR!.openPanel("inventory"));
  return { context, page };
}
const store = (page: Page) => page.evaluate(() => window.__DR!.inventory());
const normalized = (s: Snapshot) =>
  sorted(
    s.inventory.map((i) => ({
      id: i.id,
      name: i.name,
      quantity: i.slot_info.quantity,
      equipped: i.slot_info.equipped ?? false,
      type: i.type,
    })),
  );
async function converged(page: Page, s: Snapshot) {
  await expect
    .poll(
      async () =>
        sorted(
          (await store(page)).map((i) => ({
            id: i.id,
            name: i.name,
            quantity: i.quantity,
            equipped: (i as { equipped?: boolean }).equipped ?? false,
            type: (i as { type?: string }).type,
          })),
        ),
      { timeout: 12000 },
    )
    .toEqual(normalized(s));
}

test("auth boundary uses only JWT identity and agrees with Python full inventory", async ({
  testUser,
  testCharacter: _,
}) => {
  await seed(testUser.playerId);
  expect((await fetch(`${API_ORIGIN}/api/inventory`)).status).toBe(401);
  expect(
    (await fetch(`${API_ORIGIN}/api/inventory`, { headers: { Authorization: "Bearer invalid" } }))
      .status,
  ).toBe(401);
  const s = await inventory(testUser.token, "?player_id=someone-else");
  expect(s.player_id).toBe(testUser.playerId);
  expect(s.inventory).toHaveLength(5);
  expect(s.inventory.find((i) => i.id === "hollow_bone_fragment")?.image_url).toMatch(
    /^\/api\/assets\/images\/img_[a-f0-9]{16}$/,
  );
  expect(sorted(s.inventory)).toEqual(sorted(pythonInventory(testUser.playerId)));
  expect(s.inventory.find((i) => i.id === "crystal_flask")?.type).toBe("equipment");
});

test("HTTP crafting and keep update two subscribed same-player HUDs; other player stays unchanged", async ({
  browser,
  testUser,
  testCharacter: _,
}) => {
  await seed(testUser.playerId);
  const email = `inventory-${crypto.randomUUID()}@example.com`;
  const [{ id: accountId }] = await queryDb<{ id: string }>(
    "INSERT INTO accounts(email) VALUES($1) RETURNING id",
    [email],
  );
  await queryDb(
    "INSERT INTO auth_codes(account_id,code,expires_at) VALUES($1,'123456',now()+interval '10 minutes')",
    [accountId],
  );
  const auth = await fetch(`${API_ORIGIN}/api/auth/verify-code`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code: "123456" }),
  });
  expect(auth.ok).toBe(true);
  const other = (await auth.json()) as { token: string; player_id: string; account_id: string };
  await seed(other.player_id, true);
  const a1 = await device(browser, testUser),
    a2 = await device(browser, testUser),
    b = await device(browser, {
      token: other.token,
      playerId: other.player_id,
      accountId: other.account_id,
    });
  try {
    const before = await inventory(testUser.token);
    const otherBefore = await inventory(other.token);
    await converged(a1.page, before);
    await converged(a2.page, before);
    await converged(b.page, otherBefore);
    if (process.env.INVENTORY_SUPPRESS_DELIVERY === "1")
      await a2.page.route("**/api/inventory", (route) => route.abort());
    const craftResponse = a1.page.waitForResponse(
      (r) => r.url().endsWith("/api/activities") && r.request().method() === "POST",
    );
    await a1.page.evaluate(() =>
      window.__DR!.startActivity("crafting", { recipe_id: "reinforced_shield" }),
    );
    const crafted = (await (await craftResponse).json()) as Snapshot & { activity_id: string };
    expect(crafted.activity_id).toBeTruthy();
    expect(crafted.inventory.find((i) => i.id === "iron_ingot")?.slot_info.quantity).toBe(3);
    expect(crafted.inventory.some((i) => i.id === "leather_strip")).toBe(false);
    expect(sorted(crafted.inventory)).toEqual(sorted(pythonInventory(testUser.playerId)));
    await converged(a1.page, crafted);
    await converged(a2.page, crafted);
    await converged(b.page, otherBefore);
    await expect(a2.page.getByText("Crystal Flask", { exact: true })).toBeVisible();
    await queryDb("UPDATE async_activities SET data = data || $1::jsonb WHERE id=$2", [
      JSON.stringify({
        status: "resolved",
        decision_options: [{ id: "keep" }],
        outcome: { crafted_item_id: "reinforced_shield" },
      }),
      crafted.activity_id,
    ]);
    const keepResponse = a1.page.waitForResponse((r) => r.url().endsWith("/decide"));
    await a1.page.evaluate((id) => window.__DR!.submitDecision(id, "keep"), crafted.activity_id);
    const kept = (await (await keepResponse).json()) as Snapshot;
    expect(kept.inventory.find((i) => i.id === "reinforced_shield")?.slot_info.quantity).toBe(1);
    await converged(a1.page, kept);
    await converged(a2.page, kept);
    await converged(b.page, otherBefore);
    expect(sorted(kept.inventory)).toEqual(sorted(pythonInventory(testUser.playerId)));
    await expect(a2.page.getByText("Reinforced Shield", { exact: true })).toBeVisible();
    const duplicate = await fetch(`${API_ORIGIN}/api/activities/${crafted.activity_id}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${testUser.token}` },
      body: JSON.stringify({ decision_id: "keep" }),
    });
    expect(duplicate.status).toBe(400);
    expect(await duplicate.json()).not.toHaveProperty("inventory");
    const concurrentId = `concurrent_${crypto.randomUUID().replaceAll("-", "")}`;
    await queryDb("INSERT INTO async_activities(id,player_id,data) VALUES($1,$2,$3::jsonb)", [
      concurrentId,
      testUser.playerId,
      JSON.stringify({
        status: "resolved",
        activity_type: "crafting",
        decision_options: [{ id: "keep" }],
        outcome: { crafted_item_id: "reinforced_shield" },
      }),
    ]);
    const keep = () =>
      fetch(`${API_ORIGIN}/api/activities/${concurrentId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${testUser.token}` },
        body: JSON.stringify({ decision_id: "keep" }),
      });
    expect((await Promise.all([keep(), keep()])).map((r) => r.status).sort()).toEqual([200, 400]);
    expect(
      (await inventory(testUser.token)).inventory.find((i) => i.id === "reinforced_shield")
        ?.slot_info.quantity,
    ).toBe(2);
  } finally {
    await a1.context.close();
    await a2.context.close();
    await b.context.close();
  }
});

test("keep decision revalidates resolved status after the real row lock", async ({ testUser }) => {
  const id = `locked_${crypto.randomUUID().replaceAll("-", "")}`;
  await queryDb("INSERT INTO async_activities(id,player_id,data) VALUES($1,$2,$3::jsonb)", [
    id,
    testUser.playerId,
    JSON.stringify({
      status: "resolved",
      activity_type: "crafting",
      decision_options: [{ id: "keep" }],
      outcome: { crafted_item_id: "iron_sword" },
    }),
  ]);
  const conn = new pg.Client({ connectionString: requireEnvironment("DATABASE_URL") });
  await conn.connect();
  try {
    await conn.query("BEGIN");
    const {
      rows: [{ pid }],
    } = await conn.query<{ pid: number }>("SELECT pg_backend_pid() AS pid");
    await conn.query(
      "UPDATE async_activities SET data=jsonb_set(data,'{status}','\"collected\"') WHERE id=$1",
      [id],
    );
    const pending = fetch(`${API_ORIGIN}/api/activities/${id}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${testUser.token}` },
      body: JSON.stringify({ decision_id: "keep" }),
    });
    await expect
      .poll(
        async () =>
          (
            await queryDb(
              "SELECT pid FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))",
              [pid],
            )
          ).length,
      )
      .toBeGreaterThan(0);
    await conn.query("COMMIT");
    const response = await pending;
    expect(response.status).toBe(400);
    expect(await response.json()).not.toHaveProperty("inventory");
    const rows = await queryDb("SELECT item_id FROM player_inventory WHERE player_id=$1", [
      testUser.playerId,
    ]);
    expect(rows).toHaveLength(0);
  } finally {
    await conn.query("ROLLBACK");
    await conn.end();
  }
});

test("failed polling preserves HUD inventory, surfaces refresh error and retries", async ({
  browser,
  testUser,
  testCharacter: _,
}) => {
  await seed(testUser.playerId);
  const { context, page } = await device(browser, testUser);
  try {
    const initial = await inventory(testUser.token);
    await converged(page, initial);
    await page.route("**/api/inventory", (route) => route.abort());
    await expect(
      page.getByText("Inventory refresh failed. Retrying in five seconds.", { exact: true }),
    ).toBeVisible({ timeout: 10000 });
    await converged(page, initial);
    await queryDb(
      "UPDATE player_inventory SET data=jsonb_set(data,'{quantity}','6') WHERE player_id=$1 AND item_id='iron_ingot'",
      [testUser.playerId],
    );
    await page.unroute("**/api/inventory");
    await converged(page, await inventory(testUser.token));
    await expect(
      page.getByText("Inventory refresh failed. Retrying in five seconds.", { exact: true }),
    ).not.toBeVisible();
  } finally {
    await context.close();
  }
});
