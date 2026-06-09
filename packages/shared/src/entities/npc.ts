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

export interface Npc {
  id: string;
  name: string;
  tier: 1 | 2;
  role: string;
  role_archetype?: string; // links to a RoleArchetype id (M6.1)
  species: string;
  gender: string;
  age_range?: "young" | "middle" | "elder";
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
  quest_giver?: boolean; // Quest Giver overlay flag (a function, not a standalone role)
  secrets?: string[];
  faction: string;
  voice_id: string;
  voice_notes?: string;
}
