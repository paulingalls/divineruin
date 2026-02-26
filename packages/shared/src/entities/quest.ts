export interface QuestCompletionCondition {
  type: string;
  location?: string;
  required_info?: string[];
  sources?: string[];
  encounter?: string;
  outcome?: string;
  items?: string[];
  npc?: string;
  topic?: string;
}

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
  id: string | number;
  name?: string;
  objective: string;
  hints: string[];
  completion_conditions: QuestCompletionCondition | string[];
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
