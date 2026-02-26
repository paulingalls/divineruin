export interface HiddenElement {
  id: string;
  discover_skill: string;
  dc: number;
  description: string;
}

export interface LocationExit {
  destination: string;
  requires?: string;
}

export interface LocationCondition {
  description_override?: string;
  atmosphere?: string;
  atmosphere_add?: string;
  npcs_remove?: string[];
  npcs_add?: string[];
  key_features_add?: string[];
  new_encounters?: string[];
  danger_level?: number;
  danger_level_add?: number;
}

export interface Location {
  id: string;
  name: string;
  tier: 1 | 2;
  district: string;
  region: string;
  tags: string[];
  description?: string;
  atmosphere: string;
  key_features?: string[];
  hidden_elements?: HiddenElement[];
  exits: Record<string, LocationExit>;
  conditions?: Record<string, LocationCondition>;
  ambient_sounds?: string;
  ambient_sounds_night?: string;
  danger_level?: number;
}
