import { test, expect, describe } from "bun:test";
import { parseItemRow } from "./items.ts";

// Drives the production fail-loud parseItemRow (apps/server/src/items.ts) over
// content/items.json, proving every entry conforms to the widened Item interface
// from @divineruin/shared. parseItemRow is the real load boundary (loadItems calls
// it at startup); this test exercises it against the canonical content + pins its
// fail-loud behavior on malformed rows (debt aa78e26e81a8 — extracted from the
// former inline validator into the production loader, mirroring recipes.ts).
//
// Per-type structured-field REQUIREMENTS (weapon->damage_dice, armor->ac,
// equippable->durability_tier) tighten in Commit 4 alongside the content that
// satisfies them; Commit 2 validates those fields' shape only when present.

const ITEMS_PATH = new URL("../../../content/items.json", import.meta.url);

// Floor for content/items.json size — currently 29 entries. Catches silent
// attrition from bad merges/rebases. Rises to 85+ in Commit 4.
const MIN_ITEM_COUNT = 28;

async function loadItemsJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(ITEMS_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/items.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/items.json — parseItemRow conformance", () => {
  test("every entry parses via the production parseItemRow loader", async () => {
    const items = await loadItemsJson();
    expect(items.length).toBeGreaterThanOrEqual(MIN_ITEM_COUNT);
    for (const item of items) {
      const id = typeof item.id === "string" ? item.id : "<no-id>";
      // Throws with an items[<id>].<field> context on any malformed entry.
      expect(() => parseItemRow(id, item)).not.toThrow();
    }
  });

  test("parsed items round-trip their id and core fields", async () => {
    const items = await loadItemsJson();
    const sample = items.find((i) => i.id === "shortsword_basic");
    expect(sample).toBeDefined();
    const parsed = parseItemRow(sample!.id as string, sample!);
    expect(parsed.id).toBe("shortsword_basic");
    expect(parsed.type).toBe("weapon");
    expect([1, 2, 3, 4]).toContain(parsed.tier);
  });
});

describe("parseItemRow — fail-loud validation", () => {
  const base = {
    id: "test_item",
    name: "Test Item",
    tier: 1,
    type: "material",
    rarity: "common",
    tags: ["test"],
    weight: 1,
    effects: [],
    value_base: 0,
  };

  test("accepts a minimal valid row", () => {
    expect(() => parseItemRow("test_item", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseItemRow("x", null)).toThrow(/data is not an object/);
    expect(() => parseItemRow("x", [])).toThrow(/data is not an object/);
  });

  test("rejects a missing required field", () => {
    const { name: _omit, ...noName } = base;
    expect(() => parseItemRow("x", noName)).toThrow(/name/);
  });

  test("rejects a tier outside 1|2|3|4", () => {
    expect(() => parseItemRow("x", { ...base, tier: 5 })).toThrow(/tier/);
    expect(() => parseItemRow("x", { ...base, tier: 0 })).toThrow(/tier/);
  });

  test("rejects an unknown rarity", () => {
    expect(() => parseItemRow("x", { ...base, rarity: "mythic" })).toThrow(/rarity/);
  });

  test("rejects an unknown durability_tier when present", () => {
    expect(() => parseItemRow("x", { ...base, durability_tier: "reinforce" })).toThrow(
      /durability_tier/,
    );
  });

  test("accepts the 4 valid durability tiers", () => {
    for (const t of ["fragile", "standard", "reinforced", "masterwork"]) {
      expect(() =>
        parseItemRow("x", { ...base, type: "weapon", durability_tier: t }),
      ).not.toThrow();
    }
  });

  test("rejects an effect missing its type", () => {
    expect(() => parseItemRow("x", { ...base, effects: [{ target: "self" }] })).toThrow(
      /effects\[0\]\.type/,
    );
  });

  test("rejects a malformed attunement union", () => {
    expect(() => parseItemRow("x", { ...base, attunement: { kind: "sometimes" } })).toThrow(
      /attunement/,
    );
    expect(() => parseItemRow("x", { ...base, attunement: { kind: "class" } })).toThrow(
      /attunement\.class/,
    );
    expect(() => parseItemRow("x", { ...base, attunement: true })).toThrow(/attunement/);
  });

  test("accepts the 3 attunement variants", () => {
    expect(() => parseItemRow("x", { ...base, attunement: { kind: "none" } })).not.toThrow();
    expect(() => parseItemRow("x", { ...base, attunement: { kind: "required" } })).not.toThrow();
    expect(() =>
      parseItemRow("x", { ...base, attunement: { kind: "class", class: "caster" } }),
    ).not.toThrow();
  });

  test("validates art_template.vars are strings", () => {
    expect(() =>
      parseItemRow("x", {
        ...base,
        art_template: { template_id: "t", vars: { a: 1 } },
      }),
    ).toThrow(/art_template\.vars/);
  });
});
