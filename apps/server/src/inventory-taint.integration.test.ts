import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import type { Recipe, TemplateGroup } from "@divineruin/shared";
import { assertDbRequired } from "@divineruin/shared/test-util";
process.env.JWT_SECRET = "ab".repeat(32);
const { startServer } = await import("./index.ts");
import { sql } from "./db.ts";

type Snapshot = {
  player_id: string;
  inventory_revision: string;
  inventory: {
    id: string;
    tainted: boolean;
    slot_info: { quantity: number };
    image_url?: string;
  }[];
};
type StackRow = { item_id: string; tainted: boolean; data: Record<string, unknown> };

const hasDb = Boolean(process.env.DATABASE_URL);
test("required inventory database is available", () => assertDbRequired(hasDb));

describe.skipIf(!hasDb)("inventory stacks over real HTTP and Python", () => {
  const prefix = `taint_${crypto.randomUUID().replaceAll("-", "")}`;
  let server: Awaited<ReturnType<typeof startServer>>;
  let pid: string;
  let accountId: string;
  let token: string;
  const recipeIds = ["clean", "mixed", "short"].map((id) => `${prefix}_${id}`);
  const previousPort = process.env.PORT;
  const previousHost = process.env.SERVER_HOST;
  const request = (path: string, body?: unknown) =>
    fetch(new URL(path, server.url), {
      method: body ? "POST" : "GET",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  const snapshot = async () => {
    const res = await request("/api/inventory");
    expect(res.status).toBe(200);
    return (await res.json()) as Snapshot;
  };
  async function pythonSnapshot() {
    const child = Bun.spawn(
      [
        "uv",
        "run",
        "--no-sync",
        "--project",
        "../agent",
        "python",
        "-c",
        "import asyncio,json,sys; sys.path.insert(0,'../agent'); import db; from db_inventory_snapshot import get_inventory_snapshot\nasync def main():\n try: print(json.dumps(await get_inventory_snapshot(sys.argv[1])))\n finally: await db.close_all()\nasyncio.run(main())",
        pid,
      ],
      { cwd: `${import.meta.dir}/..`, stdout: "pipe", stderr: "pipe", env: process.env },
    );
    const [output, error, code] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    expect(code, error).toBe(0);
    return JSON.parse(output) as Snapshot;
  }
  async function seed(clean: number, tainted: number, equipment = false) {
    await sql`DELETE FROM async_activities WHERE player_id=${pid}`;
    await sql`DELETE FROM player_inventory WHERE player_id=${pid}`;
    for (const [taint, quantity] of [
      [false, clean],
      [true, tainted],
    ] as const) {
      if (quantity)
        await sql`INSERT INTO player_inventory(player_id,item_id,tainted,data)
        VALUES(${pid},'oak_wood',${taint},${{ quantity, equipped: false, source: "fixture" }})`;
      if (equipment)
        await sql`INSERT INTO player_inventory(player_id,item_id,tainted,data)
        VALUES(${pid},'crystal_flask',${taint},${{ quantity: 1, equipped: false, current_hits: taint ? 2 : 7 }})`;
      if (equipment)
        await sql`INSERT INTO player_inventory(player_id,item_id,tainted,data)
        VALUES(${pid},'shortsword_basic',${taint},${{ quantity: 1, equipped: false }})`;
    }
  }
  async function state() {
    return {
      snapshot: await snapshot(),
      rows: await sql<
        StackRow[]
      >`SELECT item_id,tainted,data FROM player_inventory WHERE player_id=${pid} ORDER BY item_id,tainted`,
      activities: await sql<
        { id: string; data: unknown }[]
      >`SELECT id,data FROM async_activities WHERE player_id=${pid} ORDER BY id`,
    };
  }
  const craft = (index: number) =>
    request("/api/activities", { type: "crafting", parameters: { recipe_id: recipeIds[index] } });
  beforeAll(async () => {
    const [base] = await sql<{ data: Recipe }[]>`SELECT data FROM recipes WHERE id='wooden_club'`;
    for (const [index, id] of recipeIds.entries()) {
      const data = {
        ...base!.data,
        id,
        tainted_materials: index === 1,
        materials: [
          { material_id: "oak_wood", quantity: 3, tier_minimum: 1, substitutable: false },
          ...(index === 2
            ? [{ material_id: "whetstone", quantity: 1, tier_minimum: 1, substitutable: false }]
            : []),
        ],
      };
      await sql`INSERT INTO recipes(id,data) VALUES(${id},${data})`;
    }
    process.env.PORT = "0";
    process.env.SERVER_HOST = "127.0.0.1";
    server = await startServer();
    const email = `${prefix}@example.com`;
    const [account] = await sql<
      { id: string }[]
    >`INSERT INTO accounts(email) VALUES(${email}) RETURNING id`;
    accountId = account!.id;
    await sql`INSERT INTO auth_codes(account_id,code,expires_at) VALUES(${accountId},'123456',now()+interval '10 minutes')`;
    const res = await fetch(new URL("/api/auth/verify-code", server.url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code: "123456" }),
    });
    expect(res.status).toBe(200);
    const auth = (await res.json()) as { player_id: string; token: string };
    pid = auth.player_id;
    token = auth.token;
    await sql`UPDATE players SET data=data || ${{ location_id: "accord_guild_hall", class: "warrior", proficiencies: ["crafting"] }}::jsonb WHERE player_id=${pid}`;
    await sql`INSERT INTO skill_advancement(player_id,skill_id,tier) VALUES(${pid},'crafting','expert')`;
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
    for (const id of recipeIds) await sql`DELETE FROM recipes WHERE id=${id}`;
    await server.stop(true);
    if (previousPort === undefined) delete process.env.PORT;
    else process.env.PORT = previousPort;
    if (previousHost === undefined) delete process.env.SERVER_HOST;
    else process.env.SERVER_HOST = previousHost;
  });
  test("material and gear stacks have equal ordered Python and HTTP projections", async () => {
    await seed(2, 1, true);
    const actual = await snapshot();
    expect(actual).toEqual(await pythonSnapshot());
    expect(
      actual.inventory.map((i: { id: string; tainted: boolean }) => [i.id, i.tainted]),
    ).toEqual([
      ["crystal_flask", false],
      ["crystal_flask", true],
      ["oak_wood", false],
      ["oak_wood", true],
      ["shortsword_basic", false],
      ["shortsword_basic", true],
    ]);
    expect(
      actual.inventory.filter((i) => i.id === "shortsword_basic").map((i) => i.image_url),
    ).toEqual([
      "/api/assets/images/img_9df6915b16519226",
      "/api/assets/images/img_9df6915b16519226",
    ]);
    expect(typeof actual.inventory_revision).toBe("string");
  });
  test("clean recipe refuses tainted-only holdings without any mutation", async () => {
    await seed(0, 4);
    const before = await state();
    const templates = (await (await request("/api/activity-templates")).json()) as {
      groups: TemplateGroup[];
    };
    expect(
      templates.groups.find((g) => g.type === "crafting")?.items.find((r) => r.id === recipeIds[0])
        ?.materials?.[0]?.owned,
    ).toBe(0);
    const res = await craft(0);
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Insufficient material");
    expect(await state()).toEqual(before);
  });
  test("clean consumption leaves tainted metadata and quantity unchanged", async () => {
    await seed(4, 2);
    const before = await state();
    const res = await craft(0);
    expect(res.status).toBe(200);
    const after = await state();
    expect(after.rows[1]).toEqual(before.rows[1]);
    expect(after.rows[0]!.data.quantity).toBe(1);
    const body = (await res.json()) as Snapshot;
    expect(body.inventory).toEqual(after.snapshot.inventory);
    expect(after.snapshot).toEqual(await pythonSnapshot());
  });
  test("allowed mixed craft spends tainted first and returns committed snapshot", async () => {
    await seed(2, 2);
    const templates = (await (await request("/api/activity-templates")).json()) as {
      groups: TemplateGroup[];
    };
    expect(
      templates.groups.find((g) => g.type === "crafting")?.items.find((r) => r.id === recipeIds[1])
        ?.materials?.[0]?.owned,
    ).toBe(4);
    const res = await craft(1);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Snapshot;
    const actual = await snapshot();
    expect(
      actual.inventory.map((i: { tainted: boolean; slot_info: { quantity: number } }) => [
        i.tainted,
        i.slot_info.quantity,
      ]),
    ).toEqual([[false, 1]]);
    expect(body.inventory).toEqual(actual.inventory);
    expect(body.inventory_revision).toBe(actual.inventory_revision);
    expect(actual).toEqual(await pythonSnapshot());
  });
  test("later short ingredient leaves earlier stacks and revision unchanged", async () => {
    await seed(4, 2);
    const before = await state();
    expect((await craft(2)).status).toBe(400);
    expect(await state()).toEqual(before);
  });
  test("activity insert failure rolls back stack deductions and revision", async () => {
    await seed(4, 2);
    const before = await state();
    await sql.unsafe(
      `CREATE FUNCTION ${prefix}_refuse() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.player_id = '${pid}' THEN RAISE EXCEPTION 'fixture insert failure'; END IF; RETURN NEW; END $$`,
    );
    await sql.unsafe(
      `CREATE TRIGGER ${prefix}_refuse BEFORE INSERT ON async_activities FOR EACH ROW EXECUTE FUNCTION ${prefix}_refuse()`,
    );
    try {
      expect((await craft(0)).status).toBe(500);
      expect(await state()).toEqual(before);
    } finally {
      await sql.unsafe(`DROP TRIGGER ${prefix}_refuse ON async_activities`);
      await sql.unsafe(`DROP FUNCTION ${prefix}_refuse()`);
    }
  });
});
