import { test, expect, describe } from "bun:test";
import { assertDbRequired } from "@divineruin/shared/test-util";
import { TERRAIN_PROPERTIES } from "@divineruin/shared";
import { startServer } from "./index.ts";
import { sql } from "./db.ts";
import { getLocation, listLocations, setLocations } from "./locations.ts";

const hasDb = Boolean(process.env.DATABASE_URL);
test("required DB is available", () => assertDbRequired(hasDb));

describe.skipIf(!hasDb)("terrain startup", () => {
  async function withRows(rows: Record<string, unknown>[], check: () => Promise<void>) {
    const previous = new Map(listLocations().map((row) => [row.id, row]));
    const port = process.env.PORT;
    const host = process.env.SERVER_HOST;
    process.env.PORT = "0";
    process.env.SERVER_HOST = "127.0.0.1";
    try {
      for (const row of rows) {
        await sql`INSERT INTO locations (id, data) VALUES (${row.id}, ${row})`;
      }
      await check();
    } finally {
      for (const row of rows) await sql`DELETE FROM locations WHERE id = ${row.id}`;
      setLocations(previous);
      if (port === undefined) delete process.env.PORT;
      else process.env.PORT = port;
      if (host === undefined) delete process.env.SERVER_HOST;
      else process.env.SERVER_HOST = host;
    }
  }
  const base = {
    name: "Terrain test",
    tier: 1,
    district: "test",
    region: "test",
    atmosphere: "wind",
    tags: [],
    exits: {},
  };

  test("all ten terrains reach HTTP readiness and the registry", async () => {
    const rows = Object.entries(TERRAIN_PROPERTIES).map(([terrain, props]) => ({
      ...base,
      id: `test_terrain_${terrain}`,
      terrain,
      region_type: props.region_type,
    }));
    await withRows(rows, async () => {
      const server = await startServer();
      try {
        expect((await fetch(server.url, { method: "OPTIONS" })).status).toBe(204);
        for (const row of rows)
          expect<string | undefined>(getLocation(row.id)?.terrain).toBe(row.terrain);
      } finally {
        await server.stop(true);
      }
    });
  });

  for (const terrain of [undefined, "normal", "mountain", null, 42, "__proto__"]) {
    test(`startup refuses city terrain ${String(terrain)}`, async () => {
      const id = "test_terrain_invalid";
      await withRows([{ ...base, id, region_type: "city", terrain }], async () => {
        let error: unknown;
        try {
          const server = await startServer();
          await server.stop(true);
        } catch (caught) {
          error = caught;
        }
        expect(error).toBeInstanceOf(Error);
        expect(String(error)).toContain(id);
        expect(String(error)).toContain(terrain === undefined ? "terrain" : String(terrain));
        if (terrain === "mountain") {
          expect(String(error)).toContain("city");
          expect(String(error)).toContain("wilderness");
        }
      });
    });
  }
});
