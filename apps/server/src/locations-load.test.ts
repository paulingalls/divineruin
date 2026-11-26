import { test, expect, describe, afterAll } from "bun:test";
import { parseLocationRow, getLocation, listLocations, setLocations } from "./locations.ts";
import type { Location } from "@divineruin/shared";

const LOCATIONS_PATH = new URL("../../../content/locations.json", import.meta.url);

const items = (await Bun.file(new URL("../../../content/items.json", import.meta.url)).json()) as {
  id: string;
}[];
const itemIds = new Set(items.map(({ id }) => id));

const LOCATION_COUNT = 28;

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
      expect(() => parseLocationRow(id, row, itemIds)).not.toThrow();
    }
  });

  test("the infirmary connects to the guild hall in both directions", async () => {
    const rows = await loadLocationsJson();
    const hall = rows.find((r) => r.id === "accord_guild_hall")!;
    const infirmary = rows.find((r) => r.id === "accord_guild_infirmary")!;
    expect(infirmary).toBeDefined();
    const there = parseLocationRow("accord_guild_hall", hall, itemIds);
    const back = parseLocationRow("accord_guild_infirmary", infirmary, itemIds);
    expect(
      Object.entries(there.exits).some(
        ([key, exit]) => key !== "up" && exit.destination === back.id,
      ),
    ).toBe(true);
    expect(Object.values(back.exits).some((exit) => exit.destination === there.id)).toBe(true);
  });

  test("a location with hidden_elements round-trips all element fields", async () => {
    const rows = await loadLocationsJson();
    const market = rows.find((r) => r.id === "accord_market_square");
    expect(market).toBeDefined();
    const parsed = parseLocationRow("accord_market_square", market!, itemIds);
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
    const parsed = parseLocationRow("greyvale_ruins_entrance", ruins!, itemIds);
    const deeper = parsed.exits.deeper;
    expect(deeper).toBeDefined();
    expect(deeper!.requires).toBe(
      "veythar_seal_mark.discovered || skill_check:arcana:14 || item:greyvale_veil_fragment",
    );
  });

  test("a hidden element bound to a key_feature round-trips its attaches_to id", async () => {
    const rows = await loadLocationsJson();
    const ruins = rows.find((r) => r.id === "greyvale_ruins_entrance");
    const parsed = parseLocationRow("greyvale_ruins_entrance", ruins!, itemIds);
    const seal = parsed.hidden_elements!.find((h) => h.id === "veythar_seal_mark");
    expect(seal).toBeDefined();
    expect(seal!.attaches_to).toBe("archway");
    // The attaches_to token appears as a whole word in an advertised key_feature, so the
    // discovery is reachable via natural feature prose (concern fa6663a95762).
    expect(parsed.key_features!.some((f) => /\barchway\b/.test(f))).toBe(true);
  });
});

describe("locations accessors — loadLocations consumer chain", () => {
  async function loadParsedMap(): Promise<Map<string, Location>> {
    const rows = await loadLocationsJson();
    const map = new Map<string, Location>();
    for (const row of rows)
      map.set(row.id as string, parseLocationRow(row.id as string, row, itemIds));
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
    region_type: "city",
    terrain: "city",
    tags: ["test"],
    atmosphere: "test atmosphere",
    exits: { north: { destination: "other_location" } },
  };

  test("accepts a valid minimal location", () => {
    expect(() => parseLocationRow("test_location", base, itemIds)).not.toThrow();
  });

  test("projects valid navigation", () => {
    expect(parseLocationRow("x", { ...base, navigation: "dense_forest" }, itemIds).navigation).toBe(
      "dense_forest",
    );
  });

  for (const navigation of [null, 42, false, [], {}, ""]) {
    test(`rejects invalid navigation ${JSON.stringify(navigation)}`, () => {
      expect(() => parseLocationRow("x", { ...base, navigation }, itemIds)).toThrow(
        /locations\[x\]\.navigation/,
      );
    });
  }

  test("rejects a non-object row", () => {
    expect(() => parseLocationRow("x", null, itemIds)).toThrow(/locations\[x\]/);
    expect(() => parseLocationRow("x", [], itemIds)).toThrow(/locations\[x\]/);
  });

  test("rejects a missing required atmosphere", () => {
    const { atmosphere: _omit, ...noAtmosphere } = base;
    expect(() => parseLocationRow("x", noAtmosphere, itemIds)).toThrow(
      /locations\[x\]\.atmosphere/,
    );
  });

  test("rejects a tier outside {1, 2}", () => {
    expect(() => parseLocationRow("x", { ...base, tier: 3 }, itemIds)).toThrow(
      /locations\[x\]\.tier/,
    );
    expect(() => parseLocationRow("x", { ...base, tier: "one" }, itemIds)).toThrow(
      /locations\[x\]\.tier/,
    );
  });

  test("rejects a non-array tags and non-string tag element", () => {
    expect(() => parseLocationRow("x", { ...base, tags: "test" }, itemIds)).toThrow(
      /locations\[x\]\.tags/,
    );
    expect(() => parseLocationRow("x", { ...base, tags: ["ok", 42] }, itemIds)).toThrow(
      /locations\[x\]\.tags\[1\]/,
    );
  });

  test("rejects a non-array hidden_elements", () => {
    expect(() => parseLocationRow("x", { ...base, hidden_elements: {} }, itemIds)).toThrow(
      /locations\[x\]\.hidden_elements/,
    );
  });

  test("rejects a hidden_element missing dc", () => {
    expect(() =>
      parseLocationRow(
        "x",
        {
          ...base,
          hidden_elements: [{ id: "h", discover_skill: "perception", description: "d" }],
        },
        itemIds,
      ),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.dc/);
  });

  test("rejects a hidden_element with a non-integer dc (parity with the Python int requirement)", () => {
    expect(() =>
      parseLocationRow(
        "x",
        {
          ...base,
          hidden_elements: [{ id: "h", discover_skill: "perception", dc: 10.5, description: "d" }],
        },
        itemIds,
      ),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.dc/);
  });

  test("accepts a hidden_element with a string attaches_to", () => {
    expect(() =>
      parseLocationRow(
        "x",
        {
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
        },
        itemIds,
      ),
    ).not.toThrow();
  });

  test("rejects a hidden_element with a non-string attaches_to", () => {
    expect(() =>
      parseLocationRow(
        "x",
        {
          ...base,
          hidden_elements: [
            { id: "h", discover_skill: "perception", dc: 10, description: "d", attaches_to: 7 },
          ],
        },
        itemIds,
      ),
    ).toThrow(/locations\[x\]\.hidden_elements\[0\]\.attaches_to/);
  });

  test("rejects a non-integer danger_level (parity with the 0-3 band the danger map recognizes)", () => {
    expect(() => parseLocationRow("x", { ...base, danger_level: 2.7 }, itemIds)).toThrow(
      /locations\[x\]\.danger_level/,
    );
  });

  test("accepts an integer danger_level", () => {
    expect(() => parseLocationRow("x", { ...base, danger_level: 2 }, itemIds)).not.toThrow();
  });

  test("rejects exits that is not a record", () => {
    expect(() => parseLocationRow("x", { ...base, exits: ["north"] }, itemIds)).toThrow(
      /locations\[x\]\.exits/,
    );
  });

  test("rejects an exit missing destination or with a non-string destination", () => {
    expect(() =>
      parseLocationRow("x", { ...base, exits: { north: { requires: "gate" } } }, itemIds),
    ).toThrow(/locations\[x\]\.exits\.north\.destination/);
    expect(() =>
      parseLocationRow("x", { ...base, exits: { north: { destination: 42 } } }, itemIds),
    ).toThrow(/locations\[x\]\.exits\.north\.destination/);
  });

  test("rejects an exit.requires that is neither string nor absent", () => {
    expect(() =>
      parseLocationRow(
        "x",
        { ...base, exits: { north: { destination: "o", requires: 42 } } },
        itemIds,
      ),
    ).toThrow(/locations\[x\]\.exits\.north\.requires/);
  });

  test("accepts a gated exit with a requires string", () => {
    expect(() =>
      parseLocationRow(
        "x",
        {
          ...base,
          exits: { deeper: { destination: "inner", requires: "seal.discovered" } },
        },
        itemIds,
      ),
    ).not.toThrow();
  });
});
