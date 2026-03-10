import { test, expect, describe, afterAll } from "bun:test";

const hasDatabase = !!process.env.DATABASE_URL;
const hasRedis = !!process.env.REDIS_URL;

// Row shape returned by Bun.sql for JSONB data columns
interface DataRow {
  id?: string;
  data: Record<string, unknown>;
}

// Helper to extract the JSONB data from a single-row query result
function getData(rows: DataRow[]): Record<string, unknown> {
  return rows[0]!.data;
}

describe.skipIf(!hasDatabase)("seeded content", () => {
  const sql = Bun.sql;

  afterAll(async () => {
    await sql.close();
  });

  test("accord_market_square has required fields", async () => {
    const rows: DataRow[] = await sql`SELECT data FROM locations WHERE id = 'accord_market_square'`;
    expect(rows.length).toBe(1);

    const data = getData(rows);
    expect(data.name).toBe("Market Square");
    expect(data.description).toBeTruthy();
    expect(data.exits).toBeTruthy();
    const exits = data.exits as Record<string, unknown>;
    expect(Object.keys(exits).length).toBeGreaterThanOrEqual(2);
    expect(data.ambient_sounds).toBeTruthy();
    expect(data.hidden_elements).toBeArray();
    expect((data.hidden_elements as unknown[]).length).toBeGreaterThanOrEqual(1);
    expect(data.conditions).toBeTruthy();
  });

  test("guildmaster_torin has 3 knowledge tiers", async () => {
    const rows: DataRow[] = await sql`SELECT data FROM npcs WHERE id = 'guildmaster_torin'`;
    expect(rows.length).toBe(1);

    const data = getData(rows);
    const knowledge = data.knowledge as Record<string, unknown>;
    expect(knowledge.free).toBeArray();
    expect(knowledge["disposition >= friendly"]).toBeArray();
    expect(knowledge["disposition >= trusted"]).toBeArray();
  });

  test("greyvale_anomaly has 5 stages with completion conditions", async () => {
    const rows: DataRow[] = await sql`SELECT data FROM quests WHERE id = 'greyvale_anomaly'`;
    expect(rows.length).toBe(1);

    const data = getData(rows);
    const stages = data.stages as Array<Record<string, unknown>>;
    expect(stages).toBeArray();
    expect(stages.length).toBe(5);

    for (const stage of stages) {
      expect(stage.objective).toBeTruthy();
      expect(stage.completion_conditions).toBeTruthy();
    }
  });

  test("all location exit destinations reference valid location IDs", async () => {
    const rows: DataRow[] = await sql`SELECT id, data FROM locations`;
    const locationIds = new Set(rows.map((r) => r.id));

    for (const row of rows) {
      const exits = (row.data.exits ?? {}) as Record<string, { destination: string }>;
      for (const [_direction, exitInfo] of Object.entries(exits)) {
        expect(locationIds.has(exitInfo.destination)).toBe(true);
      }
    }
  });

  test("all 3 tier 1 NPCs exist with required fields", async () => {
    const npcIds = ["guildmaster_torin", "elder_yanna", "scholar_emris"];
    for (const id of npcIds) {
      const rows: DataRow[] = await sql`SELECT data FROM npcs WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = getData(rows);
      expect(data.personality).toBeArray();
      expect(data.speech_style).toBeTruthy();
      expect(data.voice_id).toBeTruthy();
      expect(data.schedule).toBeTruthy();
    }
  });

  test("items exist with effects", async () => {
    const itemIds = ["veythar_sealed_artifact", "hollow_bone_fragment"];
    for (const id of itemIds) {
      const rows: DataRow[] = await sql`SELECT data FROM items WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = getData(rows);
      expect(data.effects).toBeArray();
      expect((data.effects as unknown[]).length).toBeGreaterThanOrEqual(1);
    }
  });

  test("factions exist with reputation tiers", async () => {
    const factionIds = ["accord_guild", "aelindran_diaspora", "independent"];
    for (const id of factionIds) {
      const rows: DataRow[] = await sql`SELECT data FROM factions WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = getData(rows);
      expect(data.reputation_tiers).toBeTruthy();
      const tiers = data.reputation_tiers as Record<string, unknown>;
      expect(Object.keys(tiers).length).toBeGreaterThanOrEqual(3);
    }
  });
});

describe.skipIf(!hasRedis)("redis connectivity", () => {
  const redis = Bun.redis;

  afterAll(() => {
    redis.close();
  });

  test("SET/GET/DEL round-trips", async () => {
    await redis.set("__test_key", "divineruin_ok");
    const val = await redis.get("__test_key");
    expect(val).toBe("divineruin_ok");
    await redis.del("__test_key");
  });
});
