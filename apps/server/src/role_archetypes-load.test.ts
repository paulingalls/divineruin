import { test, expect, describe } from "bun:test";
import { parseRoleArchetypeRow } from "./role_archetypes.ts";

// Drives the production fail-loud parseRoleArchetypeRow over content/role_archetypes.json,
// proving every entry conforms to the shared RoleArchetype contract. Mirrors
// mentor_variants-load.test.ts. The unit-level parse + accessor behavior is pinned in
// role_archetypes.test.ts. Cardinality is a closed set (story-001): 12 base archetypes
// (incl. Shipwright) + 7 Merchant subtypes = 19, split 11 civilian / 5 military / 3 specialist.

const ROOT = new URL("../../../", import.meta.url);
const ARCHETYPES_PATH = new URL("content/role_archetypes.json", ROOT);

const ARCHETYPE_COUNT = 19;
const ROLE_TYPE_COUNTS = { civilian: 11, military: 5, specialist: 3 };
const COMBATANTS = ["guard", "soldier_ashmark", "assassin_rogue", "mage", "priest"];
const NON_COMBATANTS = ["scholar_sage", "stablemaster"];
const MERCHANT_SUBTYPES = [
  "merchant_general_goods",
  "merchant_weapons_armor",
  "merchant_alchemist",
  "merchant_jeweler",
  "merchant_exotic",
  "merchant_traveling",
  "merchant_black_market",
];

async function loadArchetypes(): Promise<Record<string, unknown>[]> {
  const raw = (await Bun.file(ARCHETYPES_PATH).json()) as unknown;
  if (!Array.isArray(raw)) throw new Error("content/role_archetypes.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/role_archetypes.json — parseRoleArchetypeRow conformance", () => {
  test(`exactly ${ARCHETYPE_COUNT} entries, each parses via the production loader`, async () => {
    const rows = await loadArchetypes();
    expect(rows).toHaveLength(ARCHETYPE_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      expect(() => parseRoleArchetypeRow(id, row)).not.toThrow();
    }
  });

  test("ids are unique", async () => {
    const ids = (await loadArchetypes()).map((r) => String(r.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("role_type split is 11 civilian / 5 military / 3 specialist", async () => {
    const counts: Record<string, number> = {};
    for (const row of await loadArchetypes()) {
      const a = parseRoleArchetypeRow(String(row.id), row);
      counts[a.role_type] = (counts[a.role_type] ?? 0) + 1;
    }
    expect(counts).toEqual(ROLE_TYPE_COUNTS);
  });

  test("combatants carry combat_stats; pure non-combatants are null", async () => {
    const byId = new Map(
      (await loadArchetypes()).map((r) => [String(r.id), parseRoleArchetypeRow(String(r.id), r)]),
    );
    for (const id of COMBATANTS) expect(byId.get(id)?.combat_stats).not.toBeNull();
    for (const id of NON_COMBATANTS) expect(byId.get(id)?.combat_stats).toBeNull();
  });

  test("merchant subtypes have distinct, non-null inventory pools", async () => {
    const byId = new Map(
      (await loadArchetypes()).map((r) => [String(r.id), parseRoleArchetypeRow(String(r.id), r)]),
    );
    const pools = MERCHANT_SUBTYPES.map((id) => byId.get(id)?.inventory_pool);
    for (const p of pools) expect(typeof p).toBe("string");
    expect(new Set(pools).size).toBe(MERCHANT_SUBTYPES.length);
  });
});
