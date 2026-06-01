import { test, expect, describe, afterAll } from "bun:test";
import { parseAbilityRow, getAbility, getArchetypeAbilities, setAbilities } from "./abilities.ts";
import type { Ability } from "@divineruin/shared";

// Drives the production fail-loud parseAbilityRow (apps/server/src/abilities.ts)
// over content/archetype_abilities.json, proving every entry conforms to the shared
// Ability contract. parseAbilityRow is the real TS load boundary (loadAbilities calls
// it at startup); this test exercises it against the canonical content, pins its
// fail-loud behavior on malformed rows, and mirrors the Python loader's vocab/cost
// assertions (apps/agent/abilities.py) so the cross-language contract is enforced on
// both sides. Cost is a {stamina, focus, scaling} object (decision m22-cost-object-schema).

const ABILITIES_PATH = new URL("../../../content/archetype_abilities.json", import.meta.url);

// content/archetype_abilities.json is a closed set (story-001): 145 abilities across the
// 18 archetypes. Exact counts catch both silent attrition from bad merges AND accidental
// additions (assumption ffd661463b5d — move these literals if story-001's content changes).
const ABILITY_COUNT = 145;
const ARCHETYPE_COUNT = 18;

async function loadAbilitiesJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(ABILITIES_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/archetype_abilities.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/archetype_abilities.json — parseAbilityRow conformance", () => {
  test(`exactly ${ABILITY_COUNT} entries, each parses via the production parseAbilityRow loader`, async () => {
    const rows = await loadAbilitiesJson();
    expect(rows).toHaveLength(ABILITY_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      // Throws with the ability id + field context on any malformed entry.
      expect(() => parseAbilityRow(id, row)).not.toThrow();
    }
  });

  test("a fixed-cost ability round-trips its id and nested cost", async () => {
    const rows = await loadAbilitiesJson();
    const strike = rows.find((r) => r.id === "warrior_devastating_strike");
    expect(strike).toBeDefined();
    const parsed = parseAbilityRow("warrior_devastating_strike", strike!);
    expect(parsed.id).toBe("warrior_devastating_strike");
    expect(parsed.archetype_id).toBe("warrior");
    expect(parsed.ability_type).toBe("core");
    expect(parsed.cost.stamina).toBeGreaterThan(0);
    expect(parsed.cost.scaling).toBeNull();
  });

  test("a pool-cost ability keeps cost{0,0} with the rule in scaling", async () => {
    // paladin_lay_on_hands: real cost is a 5xlevel HP pool, carried in scaling free-text.
    // The request_ability_activation gate (story-004) must special-case this rather than
    // read cost{0,0} as free (concern 7b34ebf86b57).
    const rows = await loadAbilitiesJson();
    const lay = rows.find((r) => r.id === "paladin_lay_on_hands");
    expect(lay).toBeDefined();
    const parsed = parseAbilityRow("paladin_lay_on_hands", lay!);
    expect(parsed.cost.stamina).toBe(0);
    expect(parsed.cost.focus).toBe(0);
    expect(parsed.cost.scaling).not.toBeNull();
  });
});

describe("abilities accessors — loadAbilities consumer chain", () => {
  // loadAbilities() reads the DB; its accessor chain (setAbilities ->
  // getAbility/getArchetypeAbilities) is the runtime API consumers use after startup.
  // Drive it against the real parsed content (parseAbilityRow per row, exactly as
  // loadAbilities does) without a live DB.
  async function loadParsedMap(): Promise<Map<string, Ability>> {
    const rows = await loadAbilitiesJson();
    const map = new Map<string, Ability>();
    for (const row of rows) map.set(row.id as string, parseAbilityRow(row.id as string, row));
    return map;
  }

  // abilities.ts is a process-shared cached module in Bun. Restore the default empty
  // registry so later tests see startup state, not this catalog.
  afterAll(() => setAbilities(new Map()));

  test("getArchetypeAbilities is non-empty for all 18 archetypes", async () => {
    const map = await loadParsedMap();
    setAbilities(map);
    const archetypeIds = new Set(Array.from(map.values()).map((a) => a.archetype_id));
    expect(archetypeIds.size).toBe(ARCHETYPE_COUNT);
    for (const id of archetypeIds) {
      expect(getArchetypeAbilities(id).length, `${id} has no abilities`).toBeGreaterThan(0);
    }
  });

  test("getAbility returns a loaded ability by id", async () => {
    setAbilities(await loadParsedMap());
    const lay = getAbility("paladin_lay_on_hands");
    expect(lay.archetype_id).toBe("paladin");
    expect(lay.name).toBe("Lay on Hands");
  });

  test("getAbility is fail-loud on an unknown id", async () => {
    setAbilities(await loadParsedMap());
    expect(() => getAbility("no_such_ability_xyz")).toThrow(/no_such_ability_xyz/);
  });

  test("getArchetypeAbilities returns an empty list for an unknown archetype", async () => {
    setAbilities(await loadParsedMap());
    expect(getArchetypeAbilities("no_such_archetype_xyz")).toEqual([]);
  });
});

describe("parseAbilityRow — fail-loud validation", () => {
  const base = {
    id: "test_ability",
    archetype_id: "warrior",
    name: "Test Ability",
    ability_type: "core",
    level_requirement: 1,
    cost: { stamina: 2, focus: 0, scaling: null },
    effect: "Does a thing.",
    narration_cue: "A thing happens.",
  };

  test("accepts a valid row", () => {
    expect(() => parseAbilityRow("test_ability", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseAbilityRow("x", null)).toThrow(/abilities\[x\]/);
    expect(() => parseAbilityRow("x", [])).toThrow(/abilities\[x\]/);
  });

  test("rejects an ability_type outside the closed set", () => {
    expect(() => parseAbilityRow("x", { ...base, ability_type: "passive" })).toThrow(
      /abilities\[x\]\.ability_type/,
    );
  });

  test("rejects a missing cost block", () => {
    const { cost: _omit, ...noCost } = base;
    expect(() => parseAbilityRow("x", noCost)).toThrow(/abilities\[x\]\.cost/);
  });

  test("rejects a non-numeric cost.stamina", () => {
    expect(() => parseAbilityRow("x", { ...base, cost: { ...base.cost, stamina: "two" } })).toThrow(
      /abilities\[x\]\.cost\.stamina/,
    );
  });

  test("rejects a non-numeric cost.focus", () => {
    expect(() => parseAbilityRow("x", { ...base, cost: { ...base.cost, focus: null } })).toThrow(
      /abilities\[x\]\.cost\.focus/,
    );
  });

  test("rejects a non-integer cost.stamina (parity with the Python int requirement)", () => {
    // Python _parse_cost requires int; a float like 2.5 must fail on the TS side too,
    // so the same shared row can't pass one loader and fail the other (concern f3f1560feb6b).
    expect(() => parseAbilityRow("x", { ...base, cost: { ...base.cost, stamina: 2.5 } })).toThrow(
      /abilities\[x\]\.cost\.stamina/,
    );
  });

  test("rejects a cost.scaling that is neither string nor null", () => {
    expect(() => parseAbilityRow("x", { ...base, cost: { ...base.cost, scaling: 7 } })).toThrow(
      /abilities\[x\]\.cost\.scaling/,
    );
  });
});
