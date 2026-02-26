export interface ReputationTier {
  threshold: number;
  effects: string[];
}

export interface Faction {
  id: string;
  name: string;
  type: string;
  description: string;
  values: string[];
  territory?: string[];
  leader?: string;
  reputation_tiers: Record<string, ReputationTier>;
  relationships?: Record<string, string>;
  world_state?: {
    current_strength: string;
    active_concerns: string[];
    recent_events: string[];
  };
}
