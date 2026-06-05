import { test, expect, describe, afterAll, beforeAll } from "bun:test";
import { getLocation, listLocations, setLocations, loadLocations } from "./locations.ts";
import { sql } from "./db.ts";

// Live-DB integration test for loadLocations() — closes concern c0f5b8ae6db5.
//
// The conformance suite (locations-load.test.ts) drives parseLocationRow over the JSON
// content and the accessor chain via setLocations, but the ACTUAL startup path —
// `SELECT id, data FROM locations` -> parseLocationRow per row -> swap the map ->
// "Loaded N locations" — had no automated coverage (only manual server-boot logging).
//
// This file runs in its OWN `bun test` invocation (see package.json test:server),
// isolated like db.test.ts: live-DB tests sharing the lazy `sql` client and the
// process-global locations registry cannot coexist with the multi-file batch (the
// shared client/state breaks across files). It runs only when DATABASE_URL is set
// (the pre-push / CI server lane); the unit lane skips it cleanly.
const hasDb = Boolean(process.env.DATABASE_URL);

describe.skipIf(!hasDb)("loadLocations — DB row-fetch path", () => {
  const testRows: Record<string, Record<string, unknown>> = {
    test_load_alpha: {
      name: "Alpha Vault",
      tier: 1,
      district: "test_district",
      region: "test_region",
      atmosphere: "cold stone",
      tags: ["test"],
      exits: { out: { destination: "test_load_beta" } },
      danger_level: 2,
    },
    test_load_beta: {
      name: "Beta Hall",
      tier: 1,
      district: "test_district",
      region: "test_region",
      atmosphere: "warm hearth",
      tags: ["test"],
      // A gated exit + a per-condition danger override — exercises the loader on the
      // M6 Stage fields (exit.requires, conditions) over the real DB JSONB column.
      exits: { back: { destination: "test_load_alpha", requires: "alpha_key.discovered" } },
      danger_level: 1,
      conditions: { time_night: { danger_level: 0 } },
    },
  };
  const testIds = Object.keys(testRows);

  beforeAll(async () => {
    for (const id of testIds) {
      // Pass the object directly — Bun.sql serializes it to jsonb. (A JSON.stringify(...)
      // ::jsonb form double-encodes into a jsonb string scalar that reads back as a string.)
      await sql`
        INSERT INTO locations (id, data) VALUES (${id}, ${testRows[id]})
        ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data
      `;
    }
  });

  afterAll(async () => {
    for (const id of testIds) await sql`DELETE FROM locations WHERE id = ${id}`;
    // Restore the default empty registry so nothing downstream sees this load.
    setLocations(new Map());
  });

  test("loadLocations fetches + parses DB rows into the accessor registry", async () => {
    await loadLocations();

    const alpha = getLocation("test_load_alpha");
    expect(alpha).toBeDefined();
    expect(alpha!.name).toBe("Alpha Vault");
    expect(alpha!.tier).toBe(1);
    expect(alpha!.danger_level).toBe(2);

    // The gated exit's requires gate round-trips through the DB JSONB -> parseLocationRow.
    const beta = getLocation("test_load_beta");
    expect(beta!.exits.back?.requires).toBe("alpha_key.discovered");
    // The per-condition danger override round-trips too (the M6 Stage conditions field).
    expect(beta!.conditions?.time_night?.danger_level).toBe(0);

    // Assert presence of the seeded ids (not an exact total) so this holds whether or not
    // the lane's DB also carries the content locations.
    const loadedIds = new Set(listLocations().map((l) => l.id));
    expect(loadedIds.has("test_load_alpha")).toBe(true);
    expect(loadedIds.has("test_load_beta")).toBe(true);
  });
});
