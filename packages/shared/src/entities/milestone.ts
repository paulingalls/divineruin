// Archetype milestone — DB-loaded content shape (M2.3). content/archetype_milestones.json
// is the single source of truth for every archetype's four-tier milestone progression: the
// Identity (L5) specialization fork and the Power (L10) / Mastery (L15) / Legend (L20)
// auto-grants. This type mirrors that JSON row shape, staying symmetric with the Python
// Milestone dataclass in apps/agent/milestones.py for cross-language parity.
//
// Records are self-contained (decision 4c0677dae1be): each embeds its granted ability text
// directly and does NOT reference archetype_abilities — milestone grants are passive combat
// flags / markers, not the activatables that table holds.

export type MilestoneTier = "identity" | "power" | "mastery" | "legend";
export type MilestoneKind = "specialization_fork" | "auto_grant";

export interface SpecializationOption {
  id: string;
  name: string;
  description: string;
}

export interface Grant {
  name: string;
  effect: string;
  flag: string | null; // combat-math marker (e.g. extra_attack); null if narrative-only
}

export interface Milestone {
  id: string;
  archetype_id: string;
  tier: MilestoneTier;
  level: number;
  kind: MilestoneKind;
  patron_deferred: boolean;
  specialization_options: SpecializationOption[];
  grant: Grant | null;
  narration_cue: string;
}
