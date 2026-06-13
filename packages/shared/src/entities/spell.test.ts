import { test, expect, describe } from "bun:test";
import type { Spell, SpellSource, SpellTier } from "./spell";

// Tests for the M3.3 Spell catalog type (content/spells.json row shape).
//
// READER-GATED MIRROR (story-005, decision spell-ts-reader-gated). The Python
// Spell dataclass (apps/agent/spells.py) carries 12 fields — the 7 below PLUS 5
// M3.3 cast-time fields (resonance_by_source, terrain_effects, audio_cue,
// concentration, level_requirement). This TS type mirrors ONLY the fields a TS
// consumer actually reads. Investigation (story-005) found ZERO TS readers of
// those 5 fields: the Spell type is server-only (parsed by apps/server spells.ts,
// only focus_cost is read — by abilities.ts cost composition), never serialized
// over REST or the LiveKit data channel, never imported by mobile/web. Adding the
// 5 fields here would be forward-wired dead state (risk
// inventory-richness-forward-wired). The Python loader stays the fail-loud SSOT.
//
// These are compile-time shape conformance tests plus a structural guard: the
// fixture pins the exact 7-field shape, so accidentally widening the interface
// (adding a field with no reader) turns this red. The 5 deliberate omissions are
// documented as asserted data, not just prose — when a real TS reader lands (e.g.
// story-007, a mobile character-sheet spell list), move the now-consumed field out
// of OMITTED_M33_FIELDS and into the interface in the same change.

const arcaneBolt: Spell = {
  id: "arcane_bolt",
  name: "Arcane Bolt",
  source: "arcane",
  spell_tier: "cantrip",
  focus_cost: 0,
  mechanics: "Ranged spell attack for 1d10 force damage. Scales with level.",
  narration_cue: "A dart of raw force snaps from your fingertips.",
};

// The exact field set the TS type mirrors — the fields a TS consumer reads.
const SPELL_FIELDS = [
  "id",
  "name",
  "source",
  "spell_tier",
  "focus_cost",
  "mechanics",
  "narration_cue",
] as const;

// M3.3 fields present on the Python Spell dataclass but INTENTIONALLY omitted
// here for lack of any TS reader (decision spell-ts-reader-gated). Each entry
// records why it has no TS consumer today; add it to the interface only when a
// reader lands.
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
    field: "level_requirement",
    reason:
      "catalog Level column; tier gating lives in Python leveling.MIN_LEVEL_BY_SPELL_TIER, no TS reader",
  },
];

describe("Spell — content/spells.json row shape (reader-gated TS mirror)", () => {
  test("a 7-field spell compiles and reads back", () => {
    expect(arcaneBolt.id).toBe("arcane_bolt");
    expect(arcaneBolt.source).toBe("arcane");
    expect(arcaneBolt.spell_tier).toBe("cantrip");
    expect(arcaneBolt.focus_cost).toBe(0);
    expect(arcaneBolt.mechanics).toContain("force damage");
    expect(arcaneBolt.narration_cue).toContain("force");
  });

  test("the TS Spell mirrors exactly the 7 reader-backed fields", () => {
    // Structural guard: if the interface is widened, the fixture gains a key and
    // this fails — forcing a reader-or-revert decision (no forward-wired dead state).
    expect(Object.keys(arcaneBolt).sort()).toEqual([...SPELL_FIELDS].sort());
  });

  test("the 5 M3.3 fields are intentionally omitted for lack of a TS reader", () => {
    const omitted = OMITTED_M33_FIELDS.map((o) => o.field);
    expect(omitted).toEqual([
      "resonance_by_source",
      "terrain_effects",
      "audio_cue",
      "concentration",
      "level_requirement",
    ]);
    // None of the omitted fields leaked onto the mirrored shape.
    for (const field of omitted) {
      expect(Object.keys(arcaneBolt)).not.toContain(field);
    }
    // Every omission carries a documented reason.
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
