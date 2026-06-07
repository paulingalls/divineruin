import { test, expect, describe } from "bun:test";
import { parseMentorVariantRow } from "./mentor_variants.ts";

// Drives the production fail-loud parseMentorVariantRow over content/mentor_variants.json,
// proving every entry conforms to the shared MentorVariant contract and cross-references
// real base abilities + mentor NPCs. Mirrors spells-load.test.ts. The unit-level parse +
// accessor behavior is pinned in mentor_variants.test.ts.

const ROOT = new URL("../../../", import.meta.url);
const VARIANTS_PATH = new URL("content/mentor_variants.json", ROOT);
const ABILITIES_PATH = new URL("content/archetype_abilities.json", ROOT);
const NPCS_PATH = new URL("content/npcs.json", ROOT);

// content/mentor_variants.json is a closed set (story-001): the 40 martial elective
// techniques (warrior/guardian/skirmisher/rogue/spy x 8) x 2 cultural variants. Exact
// counts catch silent attrition AND accidental additions (move these if the set changes).
const VARIANT_COUNT = 80;
const MARTIAL_ARCHETYPES = new Set(["warrior", "guardian", "skirmisher", "rogue", "spy"]);

async function loadJson<T>(url: URL): Promise<T> {
  return (await Bun.file(url).json()) as T;
}

async function loadVariants(): Promise<Record<string, unknown>[]> {
  const raw = await loadJson<unknown>(VARIANTS_PATH);
  if (!Array.isArray(raw)) throw new Error("content/mentor_variants.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/mentor_variants.json — parseMentorVariantRow conformance", () => {
  test(`exactly ${VARIANT_COUNT} entries, each parses via the production loader`, async () => {
    const rows = await loadVariants();
    expect(rows).toHaveLength(VARIANT_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      expect(() => parseMentorVariantRow(id, row)).not.toThrow();
    }
  });

  test("ids are unique", async () => {
    // Seed upserts by id, so a duplicate id silently seeds <80 distinct DB rows
    // while the count and 2-per-technique checks still pass. Pin uniqueness here.
    const rows = await loadVariants();
    const ids = rows.map((row) => String(row.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  test("every ability_id is a real martial elective technique", async () => {
    const abilities =
      await loadJson<{ id: string; archetype_id: string; ability_type: string }[]>(ABILITIES_PATH);
    const martialElectives = new Set(
      abilities
        .filter((a) => MARTIAL_ARCHETYPES.has(a.archetype_id) && a.ability_type === "elective")
        .map((a) => a.id),
    );
    for (const row of await loadVariants()) {
      const variant = parseMentorVariantRow(String(row.id), row);
      expect(
        martialElectives.has(variant.ability_id),
        `${variant.id} -> unknown elective ${variant.ability_id}`,
      ).toBe(true);
    }
  });

  test("every mentor_id is an existing NPC", async () => {
    const npcs = await loadJson<{ id: string }[]>(NPCS_PATH);
    const npcIds = new Set(npcs.map((n) => n.id));
    for (const row of await loadVariants()) {
      const variant = parseMentorVariantRow(String(row.id), row);
      expect(
        npcIds.has(variant.mentor_id),
        `${variant.id} -> unknown mentor ${variant.mentor_id}`,
      ).toBe(true);
    }
  });

  test("every martial elective has exactly 2 variants (the swap-rule guarantee)", async () => {
    const byAbility = new Map<string, number>();
    for (const row of await loadVariants()) {
      const variant = parseMentorVariantRow(String(row.id), row);
      byAbility.set(variant.ability_id, (byAbility.get(variant.ability_id) ?? 0) + 1);
    }
    expect(byAbility.size).toBe(40);
    for (const [ability, count] of byAbility) {
      expect(count, `${ability} has ${count} variants, expected 2`).toBe(2);
    }
  });
});
