import { test, expect, describe, afterAll } from "bun:test";
import { parseItemRow, getItem, listItems, setItems } from "./items.ts";
import type { Item } from "@divineruin/shared";

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

// Floor for content/items.json size — 90 entries after the M5.4 catalog
// expansion (story-002). Catches silent attrition from bad merges/rebases.
const MIN_ITEM_COUNT = 85;

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

  test("has 6 Rare + 4 Legendary magic items, each with an audio_cue; Thornridge is quest_only", async () => {
    const items = await loadItemsJson();
    const magic = items
      .map((i) => parseItemRow(i.id as string, i))
      .filter((i) => i.tags.includes("magic"));
    expect(magic.filter((m) => m.rarity === "rare")).toHaveLength(6);
    expect(magic.filter((m) => m.rarity === "legendary")).toHaveLength(4);
    for (const m of magic) {
      expect(
        m.audio_cue,
        `magic item ${m.id} missing audio_cue (audio-first invariant)`,
      ).toBeTruthy();
    }
    const thornridge = magic.find((m) => m.id === "thornridges_stand");
    expect(thornridge?.quest_only).toBe(true);
  });

  test("every weapon has damage_dice, every armor/shield has ac, every equippable has durability_tier", async () => {
    const items = await loadItemsJson();
    const EQUIPPABLE = new Set(["weapon", "armor", "shield", "tool"]);
    for (const item of items) {
      const parsed = parseItemRow(item.id as string, item);
      if (parsed.type === "weapon") {
        expect(parsed.damage_dice, `${parsed.id} weapon missing damage_dice`).toBeDefined();
      }
      if (parsed.type === "armor" || parsed.type === "shield") {
        expect(parsed.ac, `${parsed.id} armor/shield missing ac`).toBeDefined();
      }
      if (EQUIPPABLE.has(parsed.type)) {
        expect(
          parsed.durability_tier,
          `${parsed.id} equippable missing durability_tier`,
        ).toBeDefined();
      }
    }
  });

  test("no effects[] entry duplicates a structured damage_dice/ac (legacy copies stripped)", async () => {
    // Structured damage_dice (weapons) and ac (armor/shield) are the SSOT; a legacy
    // `damage`/`ac_bonus` copy inside effects[] would silently drift (debt 07e23821109d,
    // concern 60ea16c19dfc). A consumable's genuine effect.damage (no damage_dice, e.g.
    // holy_water) is NOT a duplication and is exempt — the invariant only forbids copying
    // a structured field's value into effects[].
    const items = await loadItemsJson();
    const offenders: string[] = [];
    for (const item of items) {
      const parsed = parseItemRow(item.id as string, item);
      const effects = Array.isArray(item.effects)
        ? (item.effects as Record<string, unknown>[])
        : [];
      for (const eff of effects) {
        if ("damage" in eff && parsed.damage_dice !== undefined) {
          offenders.push(`${parsed.id}.effects[].damage`);
        }
        if ("ac_bonus" in eff && parsed.ac !== undefined) {
          offenders.push(`${parsed.id}.effects[].ac_bonus`);
        }
      }
    }
    expect(offenders, `legacy effect copies still present: ${offenders.join(", ")}`).toEqual([]);
  });
});

describe("items accessors — loadItems consumer chain", () => {
  // loadItems() reads the DB; its accessor chain (setItems -> getItem/listItems) is the
  // runtime API every consumer uses after startup. Drive that chain against the real
  // parsed catalog (parseItemRow per row, exactly as loadItems does) without a live DB —
  // the live-DB loadItems path is covered by the capstone E2E (concern aaf58ceb904a).
  async function loadParsedMap(): Promise<Map<string, Item>> {
    const items = await loadItemsJson();
    const map = new Map<string, Item>();
    for (const item of items) map.set(item.id as string, parseItemRow(item.id as string, item));
    return map;
  }

  // items.ts is a process-shared cached module in Bun (test files run in one
  // process). Restore the default empty registry so a later no-DB test importing
  // getItem/listItems sees the startup state, not this catalog — no order coupling.
  afterAll(() => setItems(new Map()));

  test("getItem returns a populated item and listItems matches the loaded set", async () => {
    const map = await loadParsedMap();
    setItems(map);
    const sword = getItem("shortsword_basic");
    expect(sword).toBeDefined();
    expect(sword!.id).toBe("shortsword_basic");
    expect(sword!.type).toBe("weapon");
    expect(sword!.damage_dice).toBeDefined();
    expect(listItems()).toHaveLength(map.size);
    expect(new Set(listItems().map((i) => i.id))).toEqual(new Set(map.keys()));
  });

  test("getItem returns undefined for an unknown id", async () => {
    setItems(await loadParsedMap());
    expect(getItem("no_such_item_xyz")).toBeUndefined();
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
        parseItemRow("x", { ...base, type: "weapon", damage_dice: "1d6", durability_tier: t }),
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

  test("requires damage_dice on a weapon", () => {
    expect(() =>
      parseItemRow("x", { ...base, type: "weapon", durability_tier: "standard" }),
    ).toThrow(/damage_dice/);
  });

  test("requires ac on armor and shield", () => {
    expect(() =>
      parseItemRow("x", { ...base, type: "armor", durability_tier: "standard" }),
    ).toThrow(/\bac\b/);
    expect(() =>
      parseItemRow("x", { ...base, type: "shield", durability_tier: "standard" }),
    ).toThrow(/\bac\b/);
  });

  test("requires durability_tier on equippable types", () => {
    expect(() => parseItemRow("x", { ...base, type: "weapon", damage_dice: "1d6" })).toThrow(
      /durability_tier/,
    );
    expect(() => parseItemRow("x", { ...base, type: "tool" })).toThrow(/durability_tier/);
  });

  test("does not require structured fields on non-equippable types", () => {
    expect(() => parseItemRow("x", { ...base, type: "consumable" })).not.toThrow();
    expect(() => parseItemRow("x", { ...base, type: "material" })).not.toThrow();
  });
});
