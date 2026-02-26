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
  species: string;
  gender: string;
  age?: string;
  appearance?: string;
  personality: string[];
  speech_style: string;
  mannerisms?: string[];
  backstory_summary?: string;
  knowledge: NpcKnowledge;
  schedule: NpcSchedule;
  default_disposition: string;
  disposition_modifiers?: Record<string, number>;
  inventory_pool: string | null;
  secrets?: string[];
  faction: string;
  voice_id: string;
  voice_notes?: string;
}
