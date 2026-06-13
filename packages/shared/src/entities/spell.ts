// Spell catalog entry — DB-loaded content shape (M8 / M3.3 / story-001). content/spells.json
// is the single source of truth for the FULL 87-spell casting catalog. The Python Spell
// dataclass (apps/agent/spells.py) is the fail-loud SSOT and carries the complete row: the 7
// fields below PLUS 5 M3.3 cast-time fields (resonance_by_source, terrain_effects, audio_cue,
// concentration, level_requirement).
//
// READER-GATED MIRROR (story-005, decision spell-ts-reader-gated): this TS type mirrors ONLY
// the fields a TS consumer actually reads — it is NOT a 1:1 parity mirror of the Python
// dataclass. The 5 M3.3 fields are deliberately omitted because no TS code reads them: this
// type is server-only (apps/server spells.ts parses it and only focus_cost is read, by
// abilities.ts cost composition), and it is never serialized over REST or the LiveKit data
// channel nor imported by mobile/web. Adding them would be forward-wired dead state (risk
// inventory-richness-forward-wired). When a real reader lands (e.g. story-007, a mobile
// character-sheet spell list), add the consumed field here in that same change. The omissions
// are pinned and documented in spell.test.ts.
//
// SOURCE-keyed, not archetype-keyed: a spell belongs to a magic source (Arcane/Divine/Primal)
// and archetypes access it via their source binding. M3.3 (decision spell-catalog-full-casting-ssot)
// made spells.json the casting-data SSOT, superseding the earlier elective-only seam (235ae150c5d3):
// caster CORE spells now live here too. archetype_abilities `core` rows stay the ACCESS grant
// (+ per-archetype effect/narration); their Focus cost composes from this catalog at load time
// (abilities.resolveCost via spell_id), so it can't drift.

export type SpellSource = "arcane" | "divine" | "primal";
export type SpellTier = "cantrip" | "minor" | "standard" | "major" | "supreme";

export interface Spell {
  id: string;
  name: string;
  source: SpellSource;
  spell_tier: SpellTier;
  focus_cost: number;
  mechanics: string;
  narration_cue: string;
}
