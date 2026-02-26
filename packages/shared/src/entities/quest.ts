export type QuestCompletionCondition =
  | { type: "location_reached"; location: string }
  | { type: "knowledge_acquired"; required_info: string[]; sources: string[] }
  | { type: "combat_completed"; encounter: string; outcome: string }
  | { type: "item_discovered"; items: string[]; location: string }
  | { type: "npc_interaction"; npc: string; topic: string };

export interface QuestReward {
  item: string;
  quantity: number;
}

export interface QuestStageComplete {
  xp: number;
  rewards?: QuestReward[];
  world_effects: string[];
  narrative_beat?: string;
  reputation?: Record<string, number>;
  unlocks_quest?: string;
}

export interface QuestBranch {
  description?: string;
  effects?: string[];
  next_stage: string;
  world_effects?: string[];
}

export interface QuestStage {
  id: string;
  name?: string;
  objective: string;
  hints: string[];
  completion_conditions: QuestCompletionCondition;
  on_complete?: QuestStageComplete;
  branches?: Record<string, QuestBranch>;
}

export interface QuestFailureCondition {
  consequence?: string;
  days?: number;
  description?: string;
  world_effects?: string[];
  reputation?: Record<string, number>;
}

export interface Quest {
  id: string;
  name: string;
  tier: 1 | 2;
  type: string;
  description: string;
  giver: string;
  giver_context?: string;
  stages: QuestStage[];
  failure_conditions?: Record<string, QuestFailureCondition>;
  global_hints?: Record<string, string>;
}
