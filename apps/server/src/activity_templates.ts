export interface ActivityTemplate {
  id: string;
  name: string;
  activity_type: "crafting" | "training" | "companion_errand";
  duration_min_seconds: number;
  duration_max_seconds: number;
  required_params: string[];
}

export interface CraftingRecipe extends ActivityTemplate {
  activity_type: "crafting";
  required_materials: string[];
  result_item_id: string;
  result_item_name: string;
  skill: string;
  dc: number;
  npc_id: string;
}

export interface TrainingProgram extends ActivityTemplate {
  activity_type: "training";
  stat: string;
  skill?: string;
  dc: number;
  mentor_id: string;
}

export interface ErrandTemplate extends ActivityTemplate {
  activity_type: "companion_errand";
  valid_destinations: string[];
}

export const CRAFTING_RECIPES: Record<string, CraftingRecipe> = {
  iron_sword: {
    id: "iron_sword",
    name: "Iron Sword",
    activity_type: "crafting",
    duration_min_seconds: 14400,
    duration_max_seconds: 28800,
    required_params: [],
    required_materials: ["iron_ingot", "leather_strip"],
    result_item_id: "iron_sword",
    result_item_name: "Iron Sword",
    skill: "athletics",
    dc: 13,
    npc_id: "grimjaw_blacksmith",
  },
  healing_poultice: {
    id: "healing_poultice",
    name: "Healing Poultice",
    activity_type: "crafting",
    duration_min_seconds: 7200,
    duration_max_seconds: 14400,
    required_params: [],
    required_materials: ["herb_bundle"],
    result_item_id: "healing_poultice",
    result_item_name: "Healing Poultice",
    skill: "medicine",
    dc: 11,
    npc_id: "grimjaw_blacksmith",
  },
  ward_stone: {
    id: "ward_stone",
    name: "Ward Stone",
    activity_type: "crafting",
    duration_min_seconds: 21600,
    duration_max_seconds: 43200,
    required_params: [],
    required_materials: ["hollow_shard", "iron_ingot"],
    result_item_id: "ward_stone",
    result_item_name: "Ward Stone",
    skill: "arcana",
    dc: 15,
    npc_id: "grimjaw_blacksmith",
  },
  reinforced_shield: {
    id: "reinforced_shield",
    name: "Reinforced Shield",
    activity_type: "crafting",
    duration_min_seconds: 14400,
    duration_max_seconds: 28800,
    required_params: [],
    required_materials: ["iron_ingot", "iron_ingot", "leather_strip"],
    result_item_id: "reinforced_shield",
    result_item_name: "Reinforced Shield",
    skill: "athletics",
    dc: 14,
    npc_id: "grimjaw_blacksmith",
  },
};

export const TRAINING_PROGRAMS: Record<string, TrainingProgram> = {
  combat_basics: {
    id: "combat_basics",
    name: "Combat Fundamentals",
    activity_type: "training",
    duration_min_seconds: 14400,
    duration_max_seconds: 28800,
    required_params: [],
    stat: "strength",
    dc: 13,
    mentor_id: "guildmaster_torin",
  },
  endurance_training: {
    id: "endurance_training",
    name: "Endurance Training",
    activity_type: "training",
    duration_min_seconds: 14400,
    duration_max_seconds: 28800,
    required_params: [],
    stat: "constitution",
    dc: 13,
    mentor_id: "guildmaster_torin",
  },
  arcane_study: {
    id: "arcane_study",
    name: "Arcane Study",
    activity_type: "training",
    duration_min_seconds: 21600,
    duration_max_seconds: 43200,
    required_params: [],
    stat: "intelligence",
    skill: "arcana",
    dc: 14,
    mentor_id: "scholar_emris",
  },
  perception_drills: {
    id: "perception_drills",
    name: "Perception Drills",
    activity_type: "training",
    duration_min_seconds: 10800,
    duration_max_seconds: 21600,
    required_params: [],
    stat: "wisdom",
    skill: "perception",
    dc: 12,
    mentor_id: "guildmaster_torin",
  },
};

export const ERRAND_TEMPLATES: Record<string, ErrandTemplate> = {
  scout: {
    id: "scout",
    name: "Scouting Mission",
    activity_type: "companion_errand",
    duration_min_seconds: 7200,
    duration_max_seconds: 14400,
    required_params: ["destination"],
    valid_destinations: ["millhaven", "greyvale_ruins", "northern_fields", "accord_dockside"],
  },
  social: {
    id: "social",
    name: "Social Inquiry",
    activity_type: "companion_errand",
    duration_min_seconds: 3600,
    duration_max_seconds: 10800,
    required_params: ["destination"],
    valid_destinations: [
      "millhaven_inn",
      "accord_guild_hall",
      "accord_market_square",
      "accord_dockside",
    ],
  },
  acquire: {
    id: "acquire",
    name: "Acquire Supplies",
    activity_type: "companion_errand",
    duration_min_seconds: 7200,
    duration_max_seconds: 14400,
    required_params: ["destination"],
    valid_destinations: ["accord_market_square", "accord_dockside", "millhaven"],
  },
  relationship: {
    id: "relationship",
    name: "Build Relationship",
    activity_type: "companion_errand",
    duration_min_seconds: 10800,
    duration_max_seconds: 21600,
    required_params: ["destination"],
    valid_destinations: ["millhaven", "millhaven_inn", "accord_guild_hall", "accord_dockside"],
  },
};

export const VALID_ACTIVITY_TYPES = new Set(["crafting", "training", "companion_errand"]);
