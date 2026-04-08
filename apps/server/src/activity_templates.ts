import type { ActivityType } from "@divineruin/shared";
import { sql } from "./db.ts";

export interface ActivityTemplate {
  id: string;
  name: string;
  activity_type: ActivityType;
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

/** Training program config, loaded from training_programs table at startup. */
export interface TrainingProgramConfig {
  id: string;
  name: string;
  training_activity_type: import("./training_state_machine.ts").TrainingActivityType;
  stat: string;
  skill?: string;
  dc: number;
  mentor_id: string;
}

export interface ErrandTemplate extends ActivityTemplate {
  activity_type: "companion_errand";
  valid_destinations: string[];
}

// Runtime-loaded training programs (populated by loadTrainingPrograms at startup)
let trainingPrograms: ReadonlyMap<string, TrainingProgramConfig> = new Map();

export function getTrainingProgram(id: string): TrainingProgramConfig | undefined {
  return trainingPrograms.get(id);
}

export function getAllTrainingPrograms(): TrainingProgramConfig[] {
  return Array.from(trainingPrograms.values());
}

export function setTrainingPrograms(map: ReadonlyMap<string, TrainingProgramConfig>): void {
  trainingPrograms = map;
}

function parseProgramRow(id: string, raw: unknown): TrainingProgramConfig {
  if (!raw || typeof raw !== "object") {
    throw new Error(`training_programs[${id}].data is not an object`);
  }
  const data = raw as Record<string, unknown>;
  const ctx = `training_programs[${id}]`;
  const name = data.name;
  const trainingActivityType = data.training_activity_type;
  const stat = data.stat;
  const dc = data.dc;
  const mentorId = data.mentor_id;
  if (typeof name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof trainingActivityType !== "string")
    throw new Error(`${ctx}.training_activity_type is not a string`);
  if (typeof stat !== "string") throw new Error(`${ctx}.stat is not a string`);
  if (typeof dc !== "number") throw new Error(`${ctx}.dc is not a number`);
  if (typeof mentorId !== "string") throw new Error(`${ctx}.mentor_id is not a string`);
  return {
    id,
    name,
    training_activity_type: trainingActivityType as TrainingProgramConfig["training_activity_type"],
    stat,
    skill: typeof data.skill === "string" ? data.skill : undefined,
    dc,
    mentor_id: mentorId,
  };
}

export async function loadTrainingPrograms(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM training_programs
  `;
  const map = new Map<string, TrainingProgramConfig>();
  for (const row of rows) {
    map.set(row.id, parseProgramRow(row.id, row.data));
  }
  trainingPrograms = map;
  console.log(`Loaded ${map.size} training programs`);
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

export const ERRAND_TEMPLATES: Record<string, ErrandTemplate> = {
  scout: {
    id: "scout",
    name: "Scouting Mission",
    activity_type: "companion_errand",
    duration_min_seconds: 7200,
    duration_max_seconds: 14400,
    required_params: ["destination"],
    valid_destinations: ["millhaven", "greyvale_ruins_entrance", "accord_dockside"],
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
