import { test, expect, describe } from "bun:test";
import type { Npc } from "./npc";

// Conformance test for content/npcs.json (Phase 6 / story-006). The JSON row IS the
// cross-language NPC contract; this test guards the `age` field's shape independent of any
// loader and serves as the compile-time shape check for the Npc type (rows are cast to Npc[],
// so interface drift breaks `bun test`).
//
// Story-006 retires the dead `age_range` enum (young|middle|elder) — never populated, never
// read — and formalizes `age?: string`, the freeform narrative age every NPC already carries
// (e.g. "late 100s (middle-aged for a dwarf)"), flavor an enum could never hold. These asserts
// pin that reality: no row carries age_range, and age is a non-empty string the schema now owns.

const npcs = (await Bun.file(
  new URL("../../../../content/npcs.json", import.meta.url),
).json()) as Npc[];

describe("npcs.json — age schema (story-006)", () => {
  test("the catalog is non-empty", () => {
    expect(npcs.length).toBeGreaterThan(0);
  });

  test("no NPC carries the retired age_range field", () => {
    for (const n of npcs) {
      expect((n as { age_range?: unknown }).age_range).toBeUndefined();
    }
  });

  test("every NPC has a freeform, non-empty age string (no data loss)", () => {
    for (const n of npcs) {
      // n.age is typed `string | undefined` (optional) — the cast enforces that at compile time.
      expect(typeof n.age).toBe("string");
      expect((n.age ?? "").length).toBeGreaterThan(0);
    }
  });

  test("age preserves narrative flavor an enum could not hold", () => {
    const ages = npcs.map((n) => n.age);
    // The load-bearing dwarf line: species-relative aging the young|middle|elder enum can't encode.
    expect(ages).toContain("late 100s (middle-aged for a dwarf)");
    // At least one NPC's age reads as appearance-vs-true-age narrative, not a single enum bucket.
    expect(ages.some((a) => (a ?? "").startsWith("appears"))).toBe(true);
  });
});
