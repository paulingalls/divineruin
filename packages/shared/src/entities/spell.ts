// Spell catalog entry — DB-loaded content shape (M8 / story-001). content/spells.json
// is the single source of truth for the ELECTIVE spell library; this type mirrors that
// JSON row shape, staying symmetric with the Python Spell dataclass in apps/agent/spells.py
// for cross-language parity. Every field is required — spells are fully-specified content.
//
// SOURCE-keyed, not archetype-keyed: a spell belongs to a magic source (Arcane/Divine/Primal)
// and archetypes access it via their source binding. Caster CORE spells are NOT here — they
// stay archetype_abilities rows with ability_type=core (the M2.2/M2.4 seam, decision
// 235ae150c5d3). This catalog borrows Phase-3 Magic's M3.3 schema minimally and is
// forward-compatible: the JSONB data column lets M3.3 later add resonance_by_source,
// terrain_effects, audio_cue, and concentration without a migration.

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
