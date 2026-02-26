import { test, expect, describe, beforeAll, afterAll } from "bun:test";

const sql = Bun.sql;

describe("seeded content", () => {
  test("accord_market_square has required fields", async () => {
    const rows = await sql`SELECT data FROM locations WHERE id = 'accord_market_square'`;
    expect(rows.length).toBe(1);

    const data = rows[0].data;
    expect(data.name).toBe("Market Square");
    expect(data.description).toBeTruthy();
    expect(data.exits).toBeTruthy();
    expect(Object.keys(data.exits).length).toBeGreaterThanOrEqual(2);
    expect(data.ambient_sounds).toBeTruthy();
    expect(data.hidden_elements).toBeArray();
    expect(data.hidden_elements.length).toBeGreaterThanOrEqual(1);
    expect(data.conditions).toBeTruthy();
  });

  test("guildmaster_torin has 3 knowledge tiers", async () => {
    const rows = await sql`SELECT data FROM npcs WHERE id = 'guildmaster_torin'`;
    expect(rows.length).toBe(1);

    const data = rows[0].data;
    expect(data.knowledge.free).toBeArray();
    expect(data.knowledge["disposition >= friendly"]).toBeArray();
    expect(data.knowledge["disposition >= trusted"]).toBeArray();
  });

  test("greyvale_anomaly has 5 stages with completion conditions", async () => {
    const rows = await sql`SELECT data FROM quests WHERE id = 'greyvale_anomaly'`;
    expect(rows.length).toBe(1);

    const data = rows[0].data;
    expect(data.stages).toBeArray();
    expect(data.stages.length).toBe(5);

    for (const stage of data.stages) {
      expect(stage.objective).toBeTruthy();
      expect(stage.completion_conditions).toBeTruthy();
    }
  });

  test("all location exit destinations reference valid location IDs", async () => {
    const rows = await sql`SELECT id, data FROM locations`;
    const locationIds = new Set(rows.map((r: { id: string }) => r.id));

    for (const row of rows) {
      const exits = row.data.exits ?? {};
      for (const [direction, exitInfo] of Object.entries(exits)) {
        const dest = (exitInfo as { destination: string }).destination;
        expect(locationIds.has(dest)).toBe(true);
      }
    }
  });

  test("all 3 tier 1 NPCs exist with required fields", async () => {
    const npcIds = ["guildmaster_torin", "elder_yanna", "scholar_emris"];
    for (const id of npcIds) {
      const rows = await sql`SELECT data FROM npcs WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = rows[0].data;
      expect(data.personality).toBeArray();
      expect(data.speech_style).toBeTruthy();
      expect(data.voice_id).toBeTruthy();
      expect(data.schedule).toBeTruthy();
    }
  });

  test("items exist with effects", async () => {
    const itemIds = ["veythar_sealed_artifact", "hollow_bone_fragment"];
    for (const id of itemIds) {
      const rows = await sql`SELECT data FROM items WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = rows[0].data;
      expect(data.effects).toBeArray();
      expect(data.effects.length).toBeGreaterThanOrEqual(1);
    }
  });

  test("factions exist with reputation tiers", async () => {
    const factionIds = ["accord_guild", "aelindran_diaspora", "independent"];
    for (const id of factionIds) {
      const rows = await sql`SELECT data FROM factions WHERE id = ${id}`;
      expect(rows.length).toBe(1);

      const data = rows[0].data;
      expect(data.reputation_tiers).toBeTruthy();
      expect(Object.keys(data.reputation_tiers).length).toBeGreaterThanOrEqual(3);
    }
  });
});
