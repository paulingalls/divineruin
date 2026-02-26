export interface EventTrigger {
  conditions: string[];
  probability: number;
  cooldown_hours: number;
  max_occurrences_per_session?: number;
}

export interface EventEffects {
  player?: Record<string, string | number>;
  world?: Record<string, string | number>;
}

export interface EventEscalation {
  dm_instructions_override?: string;
  effects?: EventEffects;
}

export interface GameEvent {
  id: string;
  name: string;
  type: "environmental" | "encounter" | "narrative" | "divine" | "economic";
  trigger: EventTrigger;
  priority: "critical" | "important" | "routine";
  dm_instructions: string;
  effects: EventEffects;
  sound_effect?: string;
  escalation?: Record<string, EventEscalation>;
}
