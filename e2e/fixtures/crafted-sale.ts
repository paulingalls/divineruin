import { spawn } from "node:child_process";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { expect } from "@playwright/test";
import cases from "../../packages/shared/fixtures/sale-price-cases.json" with { type: "json" };
import { queryDb, type TestUser } from "./auth.js";
import { API_ORIGIN } from "../ports.js";

export const startingGold = 2.5;

export async function playerData(playerId: string) {
  const [{ data }] = await queryDb<{ data: Record<string, unknown> }>(
    "SELECT data FROM players WHERE player_id=$1",
    [playerId],
  );
  return data;
}

export async function withCraftedSale(
  user: TestUser,
  run: (sale: {
    post: () => Promise<Response>;
    expectProceeds: (response: Response) => Promise<void>;
    expectState: (goldDelta?: number) => Promise<void>;
  }) => Promise<void>,
  { missingValue = false } = {},
) {
  const sample = cases.find((row) => row.id === "crafted_fractional_gold");
  if (!sample?.item || !sample.expected)
    throw new Error("Missing crafted_fractional_gold pricing case");
  const [{ silver_per_gold }] = await queryDb<{ silver_per_gold: number }>(
    "SELECT (data->>'silver_per_gold')::numeric::float8 AS silver_per_gold FROM pricing WHERE id='economy'",
  );
  const price_sp = sample.expected.price_sp;
  const gold = price_sp / silver_per_gold;
  expect(gold).toBe(8.1);
  const key = crypto.randomUUID().replaceAll("-", "");
  const itemId = `crafted_sale_item_${key}`;
  const activityId = `crafted_sale_${key}`;

  const inventoryRows = () =>
    queryDb("SELECT * FROM player_inventory WHERE player_id=$1 ORDER BY item_id, tainted", [
      user.playerId,
    ]);
  const activity = {
    status: "resolved",
    activity_type: "crafting",
    decision_options: [{ id: "keep" }, { id: "sell" }],
    outcome: { tier: "success", crafted_item_id: itemId },
  };

  try {
    const inserted = await queryDb(
      `INSERT INTO items (id, data)
       SELECT $1, (data || $2::jsonb) - $3::text FROM items WHERE id='crystal_flask'
       RETURNING id`,
      [itemId, JSON.stringify({ ...sample.item, id: itemId }), missingValue ? "value_base" : ""],
    );
    expect(inserted).toHaveLength(1);
    await queryDb("INSERT INTO async_activities (id, player_id, data) VALUES ($1, $2, $3)", [
      activityId,
      user.playerId,
      JSON.stringify(activity),
    ]);
    const before = await playerData(user.playerId);
    expect(before.gold).toBe(startingGold);
    const inventoryBefore = await inventoryRows();

    await run({
      post: () =>
        fetch(`${API_ORIGIN}/api/activities/${activityId}/decide`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${user.token}` },
          body: JSON.stringify({ decision_id: "sell", price_sp: 9999, gold: 9999 }),
          signal: AbortSignal.timeout(10_000),
        }),
      expectProceeds: async (response) => {
        expect(response.status).toBe(200);
        expect(await response.json()).toEqual({
          id: activityId,
          status: "collected",
          decision: "sell",
          proceeds: { price_sp, gold },
        });
      },
      expectState: async (goldDelta) => {
        expect(await inventoryRows()).toEqual(inventoryBefore);
        const [saved] = await queryDb("SELECT data FROM async_activities WHERE id=$1", [
          activityId,
        ]);
        expect(saved.data).toEqual(
          goldDelta === undefined
            ? activity
            : { ...activity, status: "collected", decision: "sell" },
        );
        expect(await playerData(user.playerId)).toEqual(
          goldDelta === undefined ? before : { ...before, gold: startingGold + goldDelta },
        );
      },
    });
  } finally {
    await queryDb("DELETE FROM async_activities WHERE id=$1", [activityId]);
    await queryDb("DELETE FROM items WHERE id=$1", [itemId]);
  }
}

export async function overlapCombatReward(playerId: string, post: () => Promise<Response>) {
  const child = spawn(
    "uv",
    ["run", "--project", "../apps/agent", "python", "fixtures/crafted-sale.py", playerId],
    { stdio: "pipe" },
  );
  let stderr = "";
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => (stderr += chunk));
  child.stdin.on("error", (error) => (stderr += error.message));
  const lines = createInterface({ input: child.stdout });
  const signal = AbortSignal.timeout(10_000);
  const closed = once(child, "close").then(([status]: unknown[]) => status as number | null);
  const ready = once(lines, "line", { signal }).then(([line]: unknown[]) => Number(line));
  try {
    const pid = await Promise.race([
      ready,
      closed.then((status) => {
        throw new Error(`Combat reward exited before taking its lock (${status}): ${stderr}`);
      }),
    ]);
    expect(pid).toBeGreaterThan(0);

    const pending = post();
    let finished = false;
    void pending.finally(() => (finished = true)).catch(() => {});
    let observedOverlap = false;
    await expect
      .poll(
        async () => {
          const blocked = await queryDb(
            "SELECT pid FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))",
            [pid],
          );
          observedOverlap = blocked.length > 0;
          return observedOverlap || finished;
        },
        { timeout: 5_000 },
      )
      .toBe(true);
    child.stdin.end("commit\n");
    const exited = Promise.race([
      closed,
      delay(5_000, undefined, { ref: false }).then(() => {
        throw new Error(`Combat reward did not exit after commit: ${stderr}`);
      }),
    ]);
    const [response, status] = await Promise.all([pending, exited]);
    expect(status, stderr).toBe(0);
    return { response, observedOverlap };
  } finally {
    lines.close();
    child.stdin.destroy();
    if (child.exitCode === null) child.kill("SIGKILL");
    await closed;
  }
}
