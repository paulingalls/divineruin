import { test, expect, describe, afterAll } from "bun:test";
import {
  parseArchetypeRow,
  getArchetypeChassis,
  listArchetypes,
  setArchetypes,
} from "./archetypes.ts";
import type { Archetype } from "@divineruin/shared";

// Drives the production fail-loud parseArchetypeRow (apps/server/src/archetypes.ts)
// over content/archetypes.json, proving every entry conforms to the shared
// Archetype contract. parseArchetypeRow is the real TS load boundary (loadArchetypes
// calls it at startup); this test exercises it against the canonical content, pins
// its fail-loud behavior on malformed rows, and mirrors the Python loader's
// agent-side vocab assertions (commit 10e45b6) so the cross-language contract
// (constraint chassis-row-shape-contract) is enforced on both sides.

const ARCHETYPES_PATH = new URL("../../../content/archetypes.json", import.meta.url);

// The 18 archetypes are a closed set (M2.1). Exact count catches both silent
// attrition from bad merges AND accidental additions.
const ARCHETYPE_COUNT = 18;

// Armor is a naturally closed vocabulary (classes + non-metal qualifiers + the
// unarmored sentinel); mirrors apps/agent/tests/test_archetypes_content.py
// ARMOR_VOCAB. Weapon tokens are open-ended weapon ids, checked only for
// well-formed snake_case.
const ARMOR_VOCAB = new Set([
  "heavy",
  "medium",
  "light",
  "shield",
  "heavy_nonmetal",
  "medium_nonmetal",
  "light_nonmetal",
  "shield_nonmetal",
  "none",
]);
const TOKEN_RE = /^[a-z][a-z_]*$/;

async function loadArchetypesJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(ARCHETYPES_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/archetypes.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/archetypes.json — parseArchetypeRow conformance", () => {
  test("exactly 18 entries, each parses via the production parseArchetypeRow loader", async () => {
    const rows = await loadArchetypesJson();
    expect(rows).toHaveLength(ARCHETYPE_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      // Throws with an archetypes[<id>].<field> context on any malformed entry.
      expect(() => parseArchetypeRow(id, row)).not.toThrow();
    }
  });

  test("a parsed chassis round-trips its id and nested fields", async () => {
    const rows = await loadArchetypesJson();
    const warrior = rows.find((r) => r.id === "warrior");
    expect(warrior).toBeDefined();
    const parsed = parseArchetypeRow("warrior", warrior!);
    expect(parsed.id).toBe("warrior");
    expect(parsed.hp.category).toBe("martial");
    expect(parsed.resource.pattern).toBe("stamina_only");
    expect(parsed.resource.stamina_formula).not.toBeNull();
    expect(parsed.resource.focus_formula).toBeNull();
    expect(parsed.starting_skills.num_choices).toBeGreaterThan(0);
  });

  test("armor proficiencies are in the closed vocab; weapon tokens are well-formed", async () => {
    const rows = await loadArchetypesJson();
    for (const row of rows) {
      const c = parseArchetypeRow(row.id as string, row);
      const badArmor = c.armor_proficiencies.filter((t) => !ARMOR_VOCAB.has(t));
      expect(badArmor, `${c.id} armor_proficiencies out of vocab: ${badArmor.join(", ")}`).toEqual(
        [],
      );
      const badWeapon = c.weapon_proficiencies.filter((t) => !TOKEN_RE.test(t));
      expect(badWeapon, `${c.id} weapon_proficiencies malformed: ${badWeapon.join(", ")}`).toEqual(
        [],
      );
    }
  });
});

describe("archetypes accessors — loadArchetypes consumer chain", () => {
  // loadArchetypes() reads the DB; its accessor chain (setArchetypes ->
  // getArchetypeChassis/listArchetypes) is the runtime API consumers use after
  // startup. Drive it against the real parsed content (parseArchetypeRow per row,
  // exactly as loadArchetypes does) without a live DB.
  async function loadParsedMap(): Promise<Map<string, Archetype>> {
    const rows = await loadArchetypesJson();
    const map = new Map<string, Archetype>();
    for (const row of rows) map.set(row.id as string, parseArchetypeRow(row.id as string, row));
    return map;
  }

  // archetypes.ts is a process-shared cached module in Bun. Restore the default
  // empty registry so later tests see startup state, not this catalog.
  afterAll(() => setArchetypes(new Map()));

  test("getArchetypeChassis returns a chassis and listArchetypes matches the loaded set", async () => {
    const map = await loadParsedMap();
    setArchetypes(map);
    const warrior = getArchetypeChassis("warrior");
    expect(warrior).toBeDefined();
    expect(warrior!.id).toBe("warrior");
    expect(warrior!.hp.base).toBeGreaterThan(0);
    expect(listArchetypes()).toHaveLength(map.size);
    expect(new Set(listArchetypes().map((a) => a.id))).toEqual(new Set(map.keys()));
  });

  test("getArchetypeChassis returns undefined for an unknown id", async () => {
    setArchetypes(await loadParsedMap());
    expect(getArchetypeChassis("no_such_archetype_xyz")).toBeUndefined();
  });
});

describe("parseArchetypeRow — fail-loud validation", () => {
  const base = {
    id: "test_archetype",
    hp: { base: 10, growth: 4, category: "martial" },
    resource: {
      pattern: "stamina_only",
      stamina_formula: { base: 8, attribute: "constitution", level_divisor: 1 },
      focus_formula: null,
    },
    save_proficiencies: ["strength"],
    armor_proficiencies: ["light"],
    weapon_proficiencies: ["simple"],
    starting_skills: { options: ["athletics", "perception"], num_choices: 1 },
  };

  test("accepts a valid row", () => {
    expect(() => parseArchetypeRow("test_archetype", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseArchetypeRow("x", null)).toThrow(/archetypes\[x\]/);
    expect(() => parseArchetypeRow("x", [])).toThrow(/archetypes\[x\]/);
  });

  test("rejects a missing hp block", () => {
    const { hp: _omit, ...noHp } = base;
    expect(() => parseArchetypeRow("x", noHp)).toThrow(/archetypes\[x\]\.hp/);
  });

  test("rejects a non-numeric hp.base", () => {
    expect(() => parseArchetypeRow("x", { ...base, hp: { ...base.hp, base: "ten" } })).toThrow(
      /archetypes\[x\]\.hp\.base/,
    );
  });

  test("rejects an hp.category outside the closed set", () => {
    expect(() =>
      parseArchetypeRow("x", { ...base, hp: { ...base.hp, category: "wizardly" } }),
    ).toThrow(/archetypes\[x\]\.hp\.category/);
  });

  test("rejects a resource.pattern outside the closed set", () => {
    expect(() =>
      parseArchetypeRow("x", { ...base, resource: { ...base.resource, pattern: "mana_only" } }),
    ).toThrow(/archetypes\[x\]\.resource\.pattern/);
  });

  test("rejects a malformed formula (non-object, non-null)", () => {
    expect(() =>
      parseArchetypeRow("x", {
        ...base,
        resource: { ...base.resource, stamina_formula: 7 },
      }),
    ).toThrow(/archetypes\[x\]\.resource\.stamina_formula/);
  });

  test("rejects a formula missing a numeric base", () => {
    expect(() =>
      parseArchetypeRow("x", {
        ...base,
        resource: {
          ...base.resource,
          stamina_formula: { attribute: "constitution", level_divisor: 1 },
        },
      }),
    ).toThrow(/archetypes\[x\]\.resource\.stamina_formula\.base/);
  });

  test("rejects a formula with a non-string attribute", () => {
    expect(() =>
      parseArchetypeRow("x", {
        ...base,
        resource: {
          ...base.resource,
          stamina_formula: { base: 8, attribute: 42, level_divisor: 1 },
        },
      }),
    ).toThrow(/archetypes\[x\]\.resource\.stamina_formula\.attribute/);
  });

  test("rejects non-array proficiencies", () => {
    expect(() => parseArchetypeRow("x", { ...base, save_proficiencies: "strength" })).toThrow(
      /archetypes\[x\]\.save_proficiencies/,
    );
  });

  test("rejects a missing starting_skills block", () => {
    const { starting_skills: _omit, ...noSkills } = base;
    expect(() => parseArchetypeRow("x", noSkills)).toThrow(/archetypes\[x\]\.starting_skills/);
  });

  test("rejects a non-numeric num_choices", () => {
    expect(() =>
      parseArchetypeRow("x", {
        ...base,
        starting_skills: { options: ["athletics"], num_choices: "two" },
      }),
    ).toThrow(/archetypes\[x\]\.starting_skills\.num_choices/);
  });
});
