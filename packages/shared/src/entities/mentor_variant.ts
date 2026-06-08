// Mentor variant — DB-loaded content shape (M9 / story-001). content/
// mentor_variants.json is the single source of truth for martial style variants;
// this type mirrors that JSON row shape, staying symmetric with the Python
// MentorVariant dataclass in apps/agent/mentor_variants.py for cross-language
// parity. Every field is required — variants are fully-specified content.
//
// A variant is FULLY specified (decision m9 override shape): on activation
// (story-003) its cost/effect/narration_cue replace the base ability's wholesale.
// cost reuses the shared Cost object from the abilities layer (the same
// {stamina, focus, scaling} shape), so the activation path treats a variant's
// cost exactly like a base ability's. cultural_attribution is the DM-voiced
// origin string (e.g. "Drathian Clans technique").

import type { Cost } from "./ability";

export interface MentorVariant {
  id: string;
  ability_id: string;
  mentor_id: string;
  cost: Cost;
  effect: string;
  narration_cue: string;
  cultural_attribution: string;
}
