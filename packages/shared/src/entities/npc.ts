import type { ArchetypeService, CombatStats, Disposition } from "./role_archetype";

export interface NpcQuestKnowledge {
  quest: string;
  stage: number;
  reveals: string;
}

export interface NpcKnowledge {
  free: string[];
  quest_triggered?: NpcQuestKnowledge;
  [dispositionGate: string]: string[] | NpcQuestKnowledge | undefined;
}

export interface NpcSchedule {
  [timeRange: string]: string;
}

// Mentor-level training gate (M6.3, decision mentor-binding-shape). One block per mentor
// NPC; its requirements gate every variant that mentor teaches in content/mentor_variants.json.
// effect/narration/culture per variant live in mentor_variants.json — not duplicated here.
export interface NpcMentorRequirements {
  disposition: Disposition; // minimum standing on the canonical 5-tier ladder
  quest: string | null; // optional proving-quest id
  gold: number; // training fee
  skill: string | null; // optional "SkillName: Tier" gate, e.g. "Athletics: Trained"
}

export interface NpcMentorBinding {
  culture: string;
  training_cycles: number; // cycles beyond the base technique
  requirements: NpcMentorRequirements;
}

export interface Npc {
  id: string;
  name: string;
  tier: 1 | 2;
  role: string;
  role_archetype?: string; // links to a RoleArchetype id (M6.1)
  species: string;
  gender: string;
  age?: string; // freeform narrative age, e.g. "late 100s (middle-aged for a dwarf)" (story-006)
  appearance?: string;
  personality: string[];
  speech_style: string;
  mannerisms?: string[];
  backstory_summary?: string;
  knowledge: NpcKnowledge;
  schedule: NpcSchedule;
  default_disposition: Disposition; // canonical 5-tier ladder (story-004); see role_archetype.ts
  disposition_modifiers?: Record<string, number>;
  inventory_pool: string | null;
  services?: ArchetypeService[]; // per-NPC economy overrides (M6.1)
  price_modifier?: number; // 1.0 baseline; per-NPC override of the archetype default
  combat_stats?: CombatStats; // inlined combat block (M6.1) — see role_archetype.ts
  mentor?: NpcMentorBinding; // mentor-level training gate (M6.3); present only on mentor NPCs
  quest_giver?: boolean; // Quest Giver overlay flag (a function, not a standalone role)
  secrets?: string[];
  faction: string;
  voice_id: string;
  voice_notes?: string;
}
