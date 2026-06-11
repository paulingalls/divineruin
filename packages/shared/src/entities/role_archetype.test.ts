import { test, expect, describe } from "bun:test";
import { DISPOSITION_VALUES, ROLE_TYPE_VALUES, type RoleArchetype } from "./role_archetype";

// Conformance test for the content/role_archetypes.json catalog (Phase 6 M6.1 / story-001).
// The JSON row IS the cross-language contract the story-002 (Python) and story-003 (server)
// loaders parse fail-loud; this test guards the catalog's shape + cardinality independent of
// either loader. It also serves as the compile-time shape check for the RoleArchetype type:
// rows are cast to RoleArchetype, so interface drift breaks `tsc --noEmit` / `bun test`.
//
// Catalog shape (decision, this session): each of the 7 Merchant subtypes is its own row;
// combat variants (Elite Guard, Sergeant, etc.) nest under combat_variants[] on their base
// archetype. 19 rows total = 12 base archetypes (incl. Shipwright) + 7 merchant_* subtypes.

const catalog = (await Bun.file(
  new URL("../../../../content/role_archetypes.json", import.meta.url),
).json()) as RoleArchetype[];

const byId = new Map(catalog.map((a) => [a.id, a]));

// The 12 base archetype categories (Merchant is represented by its 7 subtypes, below).
const BASE_ARCHETYPES = [
  "blacksmith",
  "innkeeper",
  "healer_temple",
  "scholar_sage",
  "guard",
  "soldier_ashmark",
  "assassin_rogue",
  "mage",
  "priest",
  "fence",
  "stablemaster",
  "shipwright",
];

const MERCHANT_SUBTYPES = [
  "merchant_general_goods",
  "merchant_weapons_armor",
  "merchant_alchemist",
  "merchant_jeweler",
  "merchant_exotic",
  "merchant_traveling",
  "merchant_black_market",
];

// Combat-bearing archetypes carry a combat_stats block; pure non-combatants are null.
const COMBATANTS = ["guard", "soldier_ashmark", "assassin_rogue", "mage", "priest"];
const NON_COMBATANTS = ["scholar_sage", "stablemaster"];

describe("role_archetypes.json — catalog cardinality", () => {
  test("19 rows total (12 base + 7 merchant subtypes)", () => {
    expect(catalog.length).toBe(19);
  });

  test("ids are unique", () => {
    expect(byId.size).toBe(catalog.length);
  });

  test("all 12 base archetype categories are present", () => {
    for (const id of BASE_ARCHETYPES) expect(byId.has(id)).toBe(true);
  });

  test("all 7 merchant subtypes are present", () => {
    for (const id of MERCHANT_SUBTYPES) expect(byId.has(id)).toBe(true);
  });

  // DISPOSITION_VALUES is the cross-package *type* SSOT; the server re-states the same
  // ladder as a runtime array (dispositions.ts DISPOSITION_ORDER) because the barrel is
  // type-only. Pin the literal here so a tier change to DISPOSITION_VALUES that misses
  // dispositions.ts breaks one of the two pins (apps/server/src/dispositions.test.ts
  // pins the same literal against DISPOSITION_ORDER).
  test("DISPOSITION_VALUES is the canonical 5-tier ladder low->high", () => {
    expect([...DISPOSITION_VALUES]).toEqual([
      "hostile",
      "unfriendly",
      "neutral",
      "friendly",
      "trusted",
    ]);
  });
});

describe("role_archetypes.json — row shape", () => {
  test("every row has the required typed fields", () => {
    for (const a of catalog) {
      expect(typeof a.id).toBe("string");
      expect(typeof a.name).toBe("string");
      expect(ROLE_TYPE_VALUES).toContain(a.role_type);
      expect(DISPOSITION_VALUES).toContain(a.default_disposition);
      expect(Array.isArray(a.knowledge_domains)).toBe(true);
      expect(Array.isArray(a.services)).toBe(true);
      expect(typeof a.price_modifier).toBe("number");
      // inventory_pool is a pool id or explicitly null.
      expect(a.inventory_pool === null || typeof a.inventory_pool === "string").toBe(true);
      // combat_stats is a block or explicitly null (no undefined — the contract is total).
      expect(a.combat_stats === null || typeof a.combat_stats === "object").toBe(true);
    }
  });

  test("services carry a numeric-or-range cost with a sp/gp unit", () => {
    for (const a of catalog) {
      for (const s of a.services) {
        expect(typeof s.name).toBe("string");
        expect(["sp", "gp"]).toContain(s.cost_unit);
        const ok =
          typeof s.cost === "number" ||
          (typeof s.cost === "object" &&
            typeof s.cost.min === "number" &&
            typeof s.cost.max === "number");
        expect(ok).toBe(true);
      }
    }
  });
});

describe("role_archetypes.json — merchant subtypes are distinct", () => {
  test("each merchant subtype has a non-null inventory_pool, all distinct", () => {
    const pools = MERCHANT_SUBTYPES.map((id) => byId.get(id)!.inventory_pool);
    for (const p of pools) expect(typeof p).toBe("string");
    expect(new Set(pools).size).toBe(MERCHANT_SUBTYPES.length);
  });

  test("merchant price_modifiers span a range (not all identical)", () => {
    const mods = MERCHANT_SUBTYPES.map((id) => byId.get(id)!.price_modifier);
    expect(new Set(mods).size).toBeGreaterThan(1);
  });
});

describe("role_archetypes.json — combat stats", () => {
  test("combat-bearing archetypes have a full combat_stats block", () => {
    for (const id of COMBATANTS) {
      const cs = byId.get(id)!.combat_stats;
      expect(cs).not.toBeNull();
      expect(typeof cs!.hp).toBe("number");
      expect(typeof cs!.ac).toBe("number");
      expect(typeof cs!.level).toBe("number");
      expect(typeof cs!.attributes.strength).toBe("number");
      expect(Array.isArray(cs!.action_pool)).toBe(true);
      expect(cs!.action_pool.length).toBeGreaterThan(0);
    }
  });

  test("pure non-combatants have combat_stats: null", () => {
    for (const id of NON_COMBATANTS) {
      expect(byId.get(id)!.combat_stats).toBeNull();
    }
  });
});
