import { test, expect, describe } from "bun:test";
import { SETTLEMENT_SIZE_VALUES, SETTLEMENT_PERSONALITY_VALUES, type Location } from "./location";

// Conformance test for the content/locations.json catalog (Phase 6 M6.2 / story-001).
// M6.2 adds two optional Location fields — settlement_tier (population size) and personality
// (flavor) — backfilled onto the *settlement* locations so the Python agent can generate
// scaled, personality-flavored NPC populations (stories 002-004). The fields are
// agent-consumed: the TS parseLocationRow loader is an allowlist-copy parser that drops
// unknown keys, so this raw-JSON test — not the loader — guards the backfill, mirroring
// role_archetype.test.ts. Rows are cast to Location, so interface drift breaks `bun test`.
//
// settlement_tier is orthogonal to region_type (city/wilderness/dungeon): region_type picks
// the ExplorationAgent; settlement_tier sizes the population. Only populated settlements
// carry the two fields — dungeon/wilderness locations omit both.

const catalog = (await Bun.file(
  new URL("../../../../content/locations.json", import.meta.url),
).json()) as Location[];

const byId = new Map(catalog.map((l) => [l.id, l]));

// The Accord — the surviving sunward-coast trade city. All 10 district-locations share the
// city tier + prosperous personality of the one settlement they belong to.
const ACCORD_IDS = [
  "accord_market_square",
  "accord_guild_hall",
  "accord_training_hall",
  "accord_temple_row",
  "accord_dockside",
  "accord_hearthstone_tavern",
  "torin_quarters",
  "emris_study",
  "accord_forge",
  "grimjaw_quarters",
];

// Millhaven — the threatened Greyvale farming village (one inn, a few farmhouses).
const MILLHAVEN_IDS = ["millhaven", "millhaven_inn", "yanna_farmhouse"];

// Dungeon/wilderness — not settlements; both new fields stay absent.
const NON_SETTLEMENT_IDS = [
  "greyvale_ruins_entrance",
  "greyvale_ruins_inner",
  "hollow_incursion_site",
  "greyvale_ruins_exterior",
  "greyvale_wilderness_north",
  "greyvale_south_road",
];

describe("locations.json — catalog cardinality", () => {
  test("19 rows total", () => {
    expect(catalog.length).toBe(19);
  });

  test("ids are unique", () => {
    expect(byId.size).toBe(catalog.length);
  });

  test("the three id groups partition the catalog", () => {
    const groups = [...ACCORD_IDS, ...MILLHAVEN_IDS, ...NON_SETTLEMENT_IDS];
    expect(groups.length).toBe(catalog.length);
    for (const id of groups) expect(byId.has(id)).toBe(true);
  });
});

describe("locations.json — settlement enum SSOTs", () => {
  // SETTLEMENT_SIZE_VALUES mirrors apps/agent/workspace.py SettlementSize (cross-language
  // parity). Capital absent (deferred); keldaran_hold present though unused by content today.
  test("SETTLEMENT_SIZE_VALUES mirrors the Python SettlementSize enum", () => {
    expect([...SETTLEMENT_SIZE_VALUES]).toEqual([
      "hamlet",
      "village",
      "town",
      "city",
      "keldaran_hold",
    ]);
  });

  test("SETTLEMENT_PERSONALITY_VALUES is the 8 M6.2 traits", () => {
    expect([...SETTLEMENT_PERSONALITY_VALUES]).toEqual([
      "prosperous",
      "struggling",
      "military",
      "scholarly",
      "corrupt",
      "devout",
      "frontier",
      "refuge",
    ]);
  });
});

describe("locations.json — settlement backfill", () => {
  test("every Accord district is city / prosperous", () => {
    for (const id of ACCORD_IDS) {
      const l = byId.get(id)!;
      expect(l.settlement_tier).toBe("city");
      expect(l.personality).toBe("prosperous");
    }
  });

  test("every Millhaven location is village / struggling", () => {
    for (const id of MILLHAVEN_IDS) {
      const l = byId.get(id)!;
      expect(l.settlement_tier).toBe("village");
      expect(l.personality).toBe("struggling");
    }
  });

  test("non-settlement (dungeon/wilderness) locations omit both fields", () => {
    for (const id of NON_SETTLEMENT_IDS) {
      const l = byId.get(id)!;
      expect(l.settlement_tier).toBeUndefined();
      expect(l.personality).toBeUndefined();
    }
  });

  // Generic guard: any row that DOES carry the fields uses only enum-valid values, so a
  // future settlement added with a typo'd tier/personality fails here too.
  test("any present settlement_tier/personality is enum-valid", () => {
    for (const l of catalog) {
      if (l.settlement_tier !== undefined) {
        expect(SETTLEMENT_SIZE_VALUES).toContain(l.settlement_tier);
      }
      if (l.personality !== undefined) {
        expect(SETTLEMENT_PERSONALITY_VALUES).toContain(l.personality);
      }
    }
  });
});

describe("locations.json — no data loss", () => {
  test("every row keeps its required pre-existing fields", () => {
    for (const l of catalog) {
      expect(typeof l.id).toBe("string");
      expect(typeof l.name).toBe("string");
      expect(typeof l.region).toBe("string");
      expect(typeof l.atmosphere).toBe("string");
      expect(typeof l.exits).toBe("object");
    }
  });
});
