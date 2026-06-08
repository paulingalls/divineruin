export interface HiddenElement {
  id: string;
  discover_skill: string;
  dc: number;
  description: string;
  // M6: binds the element to an examinable target (a key_feature or exit id) so
  // check(skill, target) can scope discovery. Optional; the target-matching
  // contract is owned by the discovery verb (story-002).
  attaches_to?: string;
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
