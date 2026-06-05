import { test, expect, describe, afterAll } from "bun:test";
import { parseLocationRow, getLocation, listLocations, setLocations } from "./locations.ts";
import type { Location } from "@divineruin/shared";

// Drives the production fail-loud parseLocationRow (apps/server/src/locations.ts)
// over content/locations.json, proving every entry conforms to the shared Location
// contract. parseLocationRow is the real TS load boundary (loadLocations calls it at
// startup); this test exercises it against the canonical content and pins its fail-loud
// behavior on malformed rows. Locations are the M6 Stage source: hidden_element.attaches_to
// scopes discovery (story-002) and exit.requires gates traversal (story-003); this loader
// is the first to validate those fields, so the fail-loud cases below guard the schema.

const LOCATIONS_PATH = new URL("../../../content/locations.json", import.meta.url);

// content/locations.json is a closed set: 19 locations. An exact count catches both
// silent attrition from bad merges AND accidental additions (move this literal if the
// content changes).
const LOCATION_COUNT = 19;

async function loadLocationsJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(LOCATIONS_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/locations.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/locations.json — parseLocationRow conformance", () => {
  test(`exactly ${LOCATION_COUNT} entries, each parses via the production parseLocationRow loader`, async () => {
    const rows = await loadLocationsJson();
    expect(rows).toHaveLength(LOCATION_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      // Throws with the location id + field context on any malformed entry.
      expect(() => parseLocationRow(id, row)).not.toThrow();
    }
  });

  test("a location with hidden_elements round-trips all element fields", async () => {
    const rows = await loadLocationsJson();
    const market = rows.find((r) => r.id === "accord_market_square");
    expect(market).toBeDefined();
    const parsed = parseLocationRow("accord_market_square", market!);
    expect(parsed.hidden_elements).toBeDefined();
    const notice = parsed.hidden_elements!.find((h) => h.id === "guild_notice_greyvale");
    expect(notice).toBeDefined();
    expect(notice!.discover_skill).toBe("perception");
    expect(notice!.dc).toBe(10);
  });

  test("a gated exit round-trips its requires gate string", async () => {
    const rows = await loadLocationsJson();
    const ruins = rows.find((r) => r.id === "greyvale_ruins_entrance");
    expect(ruins).toBeDefined();
    const parsed = parseLocationRow("greyvale_ruins_entrance", ruins!);
    const deeper = parsed.exits.deeper;
    expect(deeper).toBeDefined();
    expect(deeper!.requires).toBe("veythar_seal_mark.discovered || skill_check:arcana:14");
  });
});

describe("locations accessors — loadLocations consumer chain", () => {
  // loadLocations() reads the DB; its accessor chain (setLocations ->
  // getLocation/listLocations) is the runtime API consumers use after startup. Drive it
  // against the real parsed content (parseLocationRow per row, exactly as loadLocations
  // does) without a live DB.
  async function loadParsedMap(): Promise<Map<string, Location>> {
    const rows = await loadLocationsJson();
    const map = new Map<string, Location>();
    for (const row of rows) map.set(row.id as string, parseLocationRow(row.id as string, row));
    return map;
  }

  // locations.ts is a process-shared cached module in Bun. Restore the default empty
  // registry so later tests see startup state, not this catalog.
  afterAll(() => setLocations(new Map()));

  test("getLocation returns a loaded location by id", async () => {
    setLocations(await loadParsedMap());
    const market = getLocation("accord_market_square");
    expect(market).toBeDefined();
    expect(market!.name).toBe("Market Square");
    expect(market!.region).toBe("sunward_coast");
  });

  test("getLocation returns undefined for an unknown id", async () => {
    setLocations(await loadParsedMap());
    expect(getLocation("no_such_location_xyz")).toBeUndefined();
  });

  test(`listLocations returns all ${LOCATION_COUNT} locations`, async () => {
    setLocations(await loadParsedMap());
    expect(listLocations()).toHaveLength(LOCATION_COUNT);
  });
});

describe("parseLocationRow — fail-loud validation", () => {
  const base = {
    id: "test_location",
    name: "Test Location",
    tier: 1,
    district: "test_district",
    region: "test_region",
    tags: ["test"],
    atmosphere: "test atmosphere",
    exits: { north: { destination: "other_location" } },
  };

  test("accepts a valid minimal location", () => {
    expect(() => parseLocationRow("test_location", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseLocationRow("x", null)).toThrow(/locations\[x\]/);
    expect(() => parseLocationRow("x", [])).toThrow(/locations\[x\]/);
  });

  test("rejects a missing required atmosphere", () => {
    const { atmosphere: _omit, ...noAtmosphere } = base;
    expect(() => parseLocationRow("x", noAtmosphere)).toThrow(/locations\[x\]\.atmosphere/);
  });

  test("rejects a tier outside {1, 2}", () => {
    expect(() => parseLocationRow("x", { ...base, tier: 3 })).toThrow(/locations\[x\]\.tier/);
    expect(() => parseLocationRow("x", { ...base, tier: "one" })).toThrow(/locations\[x\]\.tier/);
  });

  test("rejects a non-array tags and non-string tag element", () => {
    expect(() => parseLocationRow("x", { ...base, tags: "test" })).toThrow(/locations\[x\]\.tags/);
    expect(() => parseLocationRow("x", { ...base, tags: ["ok", 42] })).toThrow(
      /locations\[x\]\.tags\[1\]/,
    );
  });

  test("rejects a non-array hidden_elements", () => {
    expect(() => parseLocationRow("x", { ...base, hidden_elements: {} })).toThrow(
      /locations\[x\]\.hidden_elements/,
    );
  });

  test("rejects a hidden_element missing dc", () => {
    expect(() =>
      parseLocationRow("x", {
        ...base,
        hidden_elements: [{ id: "h", discover_skill: "perception", description: "d" }],
      }),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.dc/);
  });

  test("rejects a hidden_element with a non-integer dc (parity with the Python int requirement)", () => {
    expect(() =>
      parseLocationRow("x", {
        ...base,
        hidden_elements: [{ id: "h", discover_skill: "perception", dc: 10.5, description: "d" }],
      }),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.dc/);
  });

  test("accepts a hidden_element with a string attaches_to", () => {
    expect(() =>
      parseLocationRow("x", {
        ...base,
        hidden_elements: [
          {
            id: "h",
            discover_skill: "perception",
            dc: 10,
            description: "d",
            attaches_to: "fountain",
          },
        ],
      }),
    ).not.toThrow();
  });

  test("rejects a hidden_element with a non-string attaches_to", () => {
    expect(() =>
      parseLocationRow("x", {
        ...base,
        hidden_elements: [
          { id: "h", discover_skill: "perception", dc: 10, description: "d", attaches_to: 7 },
        ],
      }),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.attaches_to/);
  });

  test("rejects a non-integer danger_level (parity with the 0-3 band the danger map recognizes)", () => {
    expect(() => parseLocationRow("x", { ...base, danger_level: 2.7 })).toThrow(
      /locations\[x\]\.danger_level/,
    );
  });

  test("accepts an integer danger_level", () => {
    expect(() => parseLocationRow("x", { ...base, danger_level: 2 })).not.toThrow();
  });

  test("rejects exits that is not a record", () => {
    expect(() => parseLocationRow("x", { ...base, exits: ["north"] })).toThrow(
      /locations\[x\]\.exits/,
    );
  });

  test("rejects an exit missing destination or with a non-string destination", () => {
    expect(() =>
      parseLocationRow("x", { ...base, exits: { north: { requires: "gate" } } }),
    ).toThrow(/locations\[x\]\.exits\.north\.destination/);
    expect(() => parseLocationRow("x", { ...base, exits: { north: { destination: 42 } } })).toThrow(
      /locations\[x\]\.exits\.north\.destination/,
    );
  });

  test("rejects an exit.requires that is neither string nor absent", () => {
    expect(() =>
      parseLocationRow("x", { ...base, exits: { north: { destination: "o", requires: 42 } } }),
    ).toThrow(/locations\[x\]\.exits\.north\.requires/);
  });

  test("accepts a gated exit with a requires string", () => {
    expect(() =>
      parseLocationRow("x", {
        ...base,
        exits: { deeper: { destination: "inner", requires: "seal.discovered" } },
      }),
    ).not.toThrow();
  });
});
