import { test, expect, describe } from "bun:test";
import {
  TACTICAL_PREFERENCE_VALUES,
  RELATIONSHIP_TIER_VALUES,
  ATTACK_TYPE_VALUES,
  type Companion,
} from "./companion";
import { DISPOSITION_VALUES, type Attributes } from "./role_archetype";
import type { Npc } from "./npc";

// Conformance test for content/companions.json (Phase 6 M6.4 / story-001). The JSON row IS
// the cross-language contract the Python loader (story-002) parses; this test guards the
// catalog's shape, cardinality, and the scaling contract independent of any loader, and serves
// as the compile-time shape check for the Companion type (rows are cast to Companion[], so
// interface drift breaks `bun test`).
//
// Scope note: story-001 is additive — Kael is COPIED here, NOT yet removed from npcs.json (his
// ~15 Python consumers are rewired in story-004). So there is intentionally no "Kael absent
// from npcs" assertion here; the narrative-fidelity pins below guard the copy instead.

const companions = (await Bun.file(
  new URL("../../../../content/companions.json", import.meta.url),
).json()) as Companion[];

const byId = new Map(companions.map((c) => [c.id, c]));

const COMPANION_IDS = ["companion_kael", "companion_lira", "companion_tam", "companion_sable"];
const ATTRIBUTE_KEYS: (keyof Attributes)[] = [
  "strength",
  "dexterity",
  "constitution",
  "intelligence",
  "wisdom",
  "charisma",
];

describe("companions.json — cardinality", () => {
  test("exactly 4 companions", () => {
    expect(companions.length).toBe(4);
  });

  test("ids are unique and exactly Kael/Lira/Tam/Sable", () => {
    expect(byId.size).toBe(companions.length);
    expect([...byId.keys()].sort()).toEqual([...COMPANION_IDS].sort());
  });

  // Value-array unions are the type SSOT; pin the literals so a union change updates the test.
  test("TACTICAL_PREFERENCE_VALUES literal pin", () => {
    expect([...TACTICAL_PREFERENCE_VALUES]).toEqual([
      "aggressive",
      "protective",
      "cautious",
      "observational",
      "opportunistic",
    ]);
  });

  test("RELATIONSHIP_TIER_VALUES is the 5 named tiers low->high", () => {
    expect([...RELATIONSHIP_TIER_VALUES]).toEqual([
      "new",
      "warming",
      "trusted",
      "bonded",
      "legendary",
    ]);
  });

  test("ATTACK_TYPE_VALUES literal pin", () => {
    expect([...ATTACK_TYPE_VALUES]).toEqual(["melee", "ranged"]);
  });
});

describe("companions.json — row shape", () => {
  test("every companion has the required narrative + combat-identity fields", () => {
    for (const c of companions) {
      expect(typeof c.id).toBe("string");
      expect(typeof c.name).toBe("string");
      expect(typeof c.species).toBe("string");
      expect(Array.isArray(c.personality)).toBe(true);
      expect(c.personality.length).toBeGreaterThan(0);
      expect(typeof c.speech_style).toBe("string");
      expect(Array.isArray(c.knowledge.free)).toBe(true);
      expect(DISPOSITION_VALUES).toContain(c.default_disposition);
      expect(TACTICAL_PREFERENCE_VALUES).toContain(c.tactical_preference);
      expect(typeof c.speed).toBe("number");
      expect(Array.isArray(c.complements)).toBe(true);
      expect(c.complements.length).toBeGreaterThan(0);
      expect(typeof c.voice_id).toBe("string");
      // exactly 2 save proficiencies (spec: companions are proficient in 2 saves)
      expect(c.save_proficiencies.length).toBe(2);
      for (const s of c.save_proficiencies) expect(ATTRIBUTE_KEYS).toContain(s as keyof Attributes);
      // base attributes complete
      for (const k of ATTRIBUTE_KEYS) expect(typeof c.base_attributes[k]).toBe("number");
    }
  });
});

describe("companions.json — scaling contract (story-002 reads these)", () => {
  test("hp_factor is a number; Kael/Lira/Tam = 0.75, Sable = 0.50", () => {
    for (const c of companions) expect(typeof c.scaling_rules.hp_factor).toBe("number");
    expect(byId.get("companion_kael")!.scaling_rules.hp_factor).toBe(0.75);
    expect(byId.get("companion_lira")!.scaling_rules.hp_factor).toBe(0.75);
    expect(byId.get("companion_tam")!.scaling_rules.hp_factor).toBe(0.75);
    expect(byId.get("companion_sable")!.scaling_rules.hp_factor).toBe(0.5);
  });

  test("ac_thresholds are non-empty and ascending by min_level", () => {
    for (const c of companions) {
      const t = c.scaling_rules.ac_thresholds;
      expect(t.length).toBeGreaterThan(0);
      expect(t[0]!.min_level).toBe(1); // a base (L1) threshold always exists
      for (let i = 1; i < t.length; i++) {
        expect(t[i]!.min_level).toBeGreaterThan(t[i - 1]!.min_level);
      }
      for (const row of t) expect(typeof row.ac).toBe("number");
    }
  });

  test("attribute_scaling steps reference valid attributes", () => {
    for (const c of companions) {
      for (const step of c.scaling_rules.attribute_scaling) {
        expect(ATTRIBUTE_KEYS).toContain(step.attribute);
        expect(typeof step.level).toBe("number");
        expect(typeof step.amount).toBe("number");
      }
    }
  });
});

describe("companions.json — ability cardinality (spec)", () => {
  test("each has >=1 attack, >=2 passives, 2-3 actives, 0-1 reactions", () => {
    for (const c of companions) {
      expect(c.attacks.length).toBeGreaterThanOrEqual(1);
      expect(c.passives.length).toBeGreaterThanOrEqual(2);
      expect(c.actives.length).toBeGreaterThanOrEqual(2);
      expect(c.actives.length).toBeLessThanOrEqual(3);
      expect(c.reactions.length).toBeLessThanOrEqual(1);
      for (const a of c.attacks) expect(ATTACK_TYPE_VALUES).toContain(a.type);
    }
  });

  test("Sable has no reactions (avoids direct combat)", () => {
    expect(byId.get("companion_sable")!.reactions.length).toBe(0);
  });
});

describe("companions.json — Sable non-verbal", () => {
  test("Sable is non_verbal; sound_palette is owned solely by voice_registry.json (B1)", () => {
    const sable = byId.get("companion_sable")!;
    expect(sable.non_verbal).toBe(true);
    expect(sable.voice_id).toBe("COMPANION_SABLE");
    // The companion entity no longer mirrors sound_palette (debt eb08ad17f6e2); voice_registry
    // is the single owner. Cast through any since the field is gone from the Companion type.
    expect((sable as { sound_palette?: unknown }).sound_palette).toBeUndefined();
  });

  test("the verbal companions are not flagged non_verbal", () => {
    for (const id of ["companion_kael", "companion_lira", "companion_tam"]) {
      const c = byId.get(id)!;
      expect(c.non_verbal).toBeUndefined();
    }
  });
});

describe("companions.json — Kael fidelity (copied from npcs.json)", () => {
  const kael = () => byId.get("companion_kael")!;

  test("narrative subset preserved from the npcs.json source", () => {
    const k = kael();
    expect(k.name).toBe("Kael");
    expect(k.default_disposition).toBe("friendly");
    expect(k.voice_id).toBe("COMPANION_KAEL");
    // load-bearing narrative strings — a lossy copy fails here
    expect(k.personality).toContain("quietly haunted");
    expect(k.knowledge.free).toContain("caravan routes between major settlements");
    expect(k.knowledge["disposition >= trusted"]).toBeDefined();
    expect(k.secrets!.some((s) => s.includes("humming stone") || s.includes("warm stone"))).toBe(
      true,
    );
    expect(k.disposition_modifiers!["abandoned_ally"]).toBe(-4);
  });

  test("base combat line matches the M6.4 spec (AC 15, STR 15, protective)", () => {
    const k = kael();
    expect(k.tactical_preference).toBe("protective");
    expect(k.scaling_rules.ac_thresholds[0]!.ac).toBe(15);
    expect(k.base_attributes.strength).toBe(15);
    // Intercept — the defining Kael reaction
    expect(k.reactions.some((r) => r.name === "Intercept")).toBe(true);
  });

  test("companion_kael migrated out of npcs.json (story-004)", async () => {
    const npcs = (await Bun.file(
      new URL("../../../../content/npcs.json", import.meta.url),
    ).json()) as Npc[];
    expect(npcs.some((n) => n.id === "companion_kael")).toBe(false);
  });
});
