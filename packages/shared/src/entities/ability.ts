// Archetype ability — DB-loaded content shape (M2.2). content/archetype_abilities.json
// is the single source of truth for every archetype's activatable abilities; this type
// mirrors that JSON row shape (nested cost object), staying symmetric with the Python
// Ability dataclass in apps/agent/abilities.py for cross-language parity. Every field is
// required — abilities are fully-specified content.
//
// Cost is a structured object (decision m22-cost-object-schema): {stamina, focus, scaling}.
// Fixed/zero/mixed costs live in stamina+focus; variable (Divine Smite) and pool-based
// (Lay on Hands) costs put their base in stamina/focus and the human-readable rule in the
// free-text scaling field. There is NO cost_type enum — variable/pool cost is expressed
// via scaling, not a discriminator.

export type AbilityType = "core" | "reaction" | "elective";

export interface Cost {
  stamina: number;
  focus: number;
  scaling: string | null; // variable/pool cost detail (e.g. Divine Smite, Lay on Hands)
}

export interface Ability {
  id: string;
  archetype_id: string;
  name: string;
  ability_type: AbilityType;
  level_requirement: number;
  cost: Cost;
  effect: string;
  narration_cue: string;
  // Set on spell-backed caster CORE rows. The Focus cost — the one cast number shared with
  // the cast path — is NOT authored on the row; it composes from content/spells.json via this
  // id (kept single-sourced, no drift). effect/narration/level stay per-archetype. Absent on
  // non-spell rows.
  spell_id?: string;
}
