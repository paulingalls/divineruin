// Agent-only casting internals stay excluded until a TypeScript consumer needs them.

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
  verbal: boolean;
  hostile: boolean;
}
