import { test, expect, describe, afterAll } from "bun:test";
import { parseSpellRow, getSpell, getSpellsBySource, setSpells } from "./spells.ts";
import type { Spell } from "@divineruin/shared";

// Drives the production fail-loud parseSpellRow (apps/server/src/spells.ts) over
// content/spells.json, proving every entry conforms to the shared Spell contract.
// parseSpellRow is the real TS load boundary (loadSpells calls it at startup); this
// test exercises it against the canonical content, pins its fail-loud behavior on
// malformed rows, and mirrors the Python loader's vocab assertions (apps/agent/
// spells.py) so the cross-language contract is enforced on both sides. M3.3 makes
// spells.json the FULL casting-data SSOT (decision spell-catalog-full-casting-ssot),
// superseding the M8 elective-only seam (235ae150c5d3): caster core spells now live in
// the catalog too. This TS loader stays lenient on the M3.3 fields (ignores the extra
// JSONB) pending the strict-mirror work tracked as concern 26ab12def2a3.

const SPELLS_PATH = new URL("../../../content/spells.json", import.meta.url);

// content/spells.json is the full M3.3 casting catalog: 87 spells across 3 sources,
// partitioned 30 arcane / 28 divine / 29 primal (magic.md:541). Exact counts catch
// silent attrition AND accidental additions (move these literals if the catalog changes).
const SPELL_COUNT = 87;
const SOURCE_COUNT = 3;
const SOURCE_PARTITIONS: Record<string, number> = { arcane: 30, divine: 28, primal: 29 };

async function loadSpellsJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(SPELLS_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/spells.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/spells.json — parseSpellRow conformance", () => {
  test(`exactly ${SPELL_COUNT} entries, each parses via the production parseSpellRow loader`, async () => {
    const rows = await loadSpellsJson();
    expect(rows).toHaveLength(SPELL_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      expect(() => parseSpellRow(id, row)).not.toThrow();
    }
  });

  test("the catalog is partitioned 30 arcane / 28 divine / 29 primal", async () => {
    const rows = await loadSpellsJson();
    const counts: Record<string, number> = {};
    for (const row of rows) counts[String(row.source)] = (counts[String(row.source)] ?? 0) + 1;
    expect(counts).toEqual(SOURCE_PARTITIONS);
  });

  test("a major spell round-trips its id, source, tier, and focus cost", async () => {
    const rows = await loadSpellsJson();
    const fireball = rows.find((r) => r.id === "arcane_fireball");
    expect(fireball).toBeDefined();
    const parsed = parseSpellRow("arcane_fireball", fireball!);
    expect(parsed.id).toBe("arcane_fireball");
    expect(parsed.source).toBe("arcane");
    expect(parsed.spell_tier).toBe("major");
    expect(parsed.focus_cost).toBe(5);
  });

  test("the full casting catalog includes the caster core spells", async () => {
    // M3.3 (decision spell-catalog-full-casting-ssot): cast_spell/get_spell_info need data
    // for every castable spell, so the caster-core spells live in the catalog too;
    // archetype_abilities `core` rows remain as the access grant. Mirrors the Python
    // test_content_includes_caster_core_spells.
    const rows = await loadSpellsJson();
    const names = new Set(rows.map((r) => String(r.name).toLowerCase()));
    for (const core of [
      "arcane bolt",
      "sacred flame",
      "heal wounds",
      "thorn whip",
      "healing touch",
    ]) {
      expect(names.has(core), `casting catalog must carry core spell ${core}`).toBe(true);
    }
  });
});

describe("spells accessors — loadSpells consumer chain", () => {
  async function loadParsedMap(): Promise<Map<string, Spell>> {
    const rows = await loadSpellsJson();
    const map = new Map<string, Spell>();
    for (const row of rows) map.set(row.id as string, parseSpellRow(row.id as string, row));
    return map;
  }

  // spells.ts is a process-shared cached module in Bun. Restore the default empty
  // registry so later tests see startup state, not this catalog.
  afterAll(() => setSpells(new Map()));

  test("getSpellsBySource is non-empty for all 3 sources", async () => {
    const map = await loadParsedMap();
    setSpells(map);
    const sources = new Set(Array.from(map.values()).map((s) => s.source));
    expect(sources.size).toBe(SOURCE_COUNT);
    for (const source of sources) {
      expect(getSpellsBySource(source).length, `${source} has no spells`).toBeGreaterThan(0);
    }
  });

  test("getSpell returns a loaded spell by id", async () => {
    setSpells(await loadParsedMap());
    const fireball = getSpell("arcane_fireball");
    expect(fireball.source).toBe("arcane");
    expect(fireball.name).toBe("Fireball");
  });

  test("getSpell is fail-loud on an unknown id", async () => {
    setSpells(await loadParsedMap());
    expect(() => getSpell("no_such_spell_xyz")).toThrow(/no_such_spell_xyz/);
  });

  test("getSpellsBySource returns an empty list for an unknown source", async () => {
    setSpells(await loadParsedMap());
    expect(getSpellsBySource("shadow")).toEqual([]);
  });
});

describe("parseSpellRow — fail-loud validation", () => {
  const base = {
    id: "test_spell",
    name: "Test Spell",
    source: "arcane",
    spell_tier: "standard",
    focus_cost: 3,
    mechanics: "Does a thing.",
    narration_cue: "A thing happens.",
  };

  test("accepts a valid row", () => {
    expect(() => parseSpellRow("test_spell", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseSpellRow("x", null)).toThrow(/spells\[x\]/);
    expect(() => parseSpellRow("x", [])).toThrow(/spells\[x\]/);
  });

  test("rejects a source outside the closed set", () => {
    expect(() => parseSpellRow("x", { ...base, source: "shadow" })).toThrow(/spells\[x\]\.source/);
  });

  test("rejects a spell_tier outside the closed set", () => {
    expect(() => parseSpellRow("x", { ...base, spell_tier: "legendary" })).toThrow(
      /spells\[x\]\.spell_tier/,
    );
  });

  test("rejects a missing mechanics field", () => {
    const { mechanics: _omit, ...noMechanics } = base;
    expect(() => parseSpellRow("x", noMechanics)).toThrow(/spells\[x\]\.mechanics/);
  });

  test("rejects a non-integer focus_cost (parity with the Python int requirement)", () => {
    expect(() => parseSpellRow("x", { ...base, focus_cost: 2.5 })).toThrow(
      /spells\[x\]\.focus_cost/,
    );
  });
});
