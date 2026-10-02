import { test, expect, describe } from "bun:test";
import type { Spell, SpellSource, SpellTier } from "./spell";

const arcaneBolt: Spell = {
  id: "arcane_bolt",
  name: "Arcane Bolt",
  source: "arcane",
  spell_tier: "cantrip",
  focus_cost: 0,
  mechanics: "Ranged spell attack for 1d10 force damage. Scales with level.",
  narration_cue: "A dart of raw force snaps from your fingertips.",
  verbal: true,
  hostile: true,
};

const SPELL_FIELDS = {
  id: true,
  name: true,
  source: true,
  spell_tier: true,
  focus_cost: true,
  mechanics: true,
  narration_cue: true,
  verbal: true,
  hostile: true,
} as const satisfies Record<keyof Spell, true>;
const readerSpell: Required<Spell> = arcaneBolt;

const OMITTED_M33_FIELDS: ReadonlyArray<{ field: string; reason: string }> = [
  {
    field: "resonance_by_source",
    reason: "cast-resolution internal; consumed by the Python rules engine, no TS reader",
  },
  { field: "terrain_effects", reason: "Primal cast-resolution internal; no TS reader" },
  {
    field: "audio_cue",
    reason:
      "cast SFX auto-pushed by the agent; mobile plays a generic 'spell_cast' sound, not the per-spell cue",
  },
  {
    field: "concentration",
    reason:
      "M3.4 gate; no TS reader yet (a mobile spell-list concentration badge would be one — story-007)",
  },
  {
    field: "sound_id",
    reason:
      "playable key read by the Python emit + the mobile registry via the PLAY_SOUND event (story-004), not the TS Spell entity or apps/server",
  },
];

describe("Spell — content/spells.json row shape (reader-gated TS mirror)", () => {
  test("a 9-field spell compiles and reads back", () => {
    expect(arcaneBolt.id).toBe("arcane_bolt");
    expect(arcaneBolt.source).toBe("arcane");
    expect(arcaneBolt.spell_tier).toBe("cantrip");
    expect(arcaneBolt.focus_cost).toBe(0);
    expect(arcaneBolt.mechanics).toContain("force damage");
    expect(arcaneBolt.narration_cue).toContain("force");
    expect(readerSpell.verbal).toBe(true);
    expect(readerSpell.hostile).toBe(true);
  });

  test("the TS Spell mirrors exactly the 9 reader-backed fields", () => {
    expect(Object.keys(arcaneBolt).sort()).toEqual(Object.keys(SPELL_FIELDS).sort());
  });

  test("the 5 M3.3/M17 fields are intentionally omitted for lack of a TS reader", () => {
    const omitted = OMITTED_M33_FIELDS.map((o) => o.field);
    expect(omitted).toEqual([
      "resonance_by_source",
      "terrain_effects",
      "audio_cue",
      "concentration",
      "sound_id",
    ]);
    for (const field of omitted) {
      expect(Object.keys(arcaneBolt)).not.toContain(field);
    }
    for (const { reason } of OMITTED_M33_FIELDS) {
      expect(reason.length).toBeGreaterThan(0);
    }
  });

  test("SpellSource and SpellTier are the closed vocabularies the loader validates", () => {
    const sources: SpellSource[] = ["arcane", "divine", "primal"];
    const tiers: SpellTier[] = ["cantrip", "minor", "standard", "major", "supreme"];
    expect(sources).toHaveLength(3);
    expect(tiers).toHaveLength(5);
  });
});
