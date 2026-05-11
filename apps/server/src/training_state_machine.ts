/**
 * Training cycle state machine — first-half init only.
 *
 * Config (duration ranges + midpoint decisions) is loaded from the
 * training_activity_types table at startup via loadTrainingActivityTypes().
 * The Python async worker handles midpoint and completion transitions;
 * the TS server only needs first-half init and decision option display.
 *
 * Uses `transition_at` (not `decision_at`) to match db_training.py query convention.
 */

import { sql } from "./db.ts";

export type TrainingActivityType =
  | "spell_cantrip"
  | "spell_standard"
  | "spell_major"
  | "spell_supreme"
  | "recipe_study"
  | "technique_base"
  | "technique_mentor"
  | "skill_practice";

export interface MidpointOption {
  id: string;
  label: string;
}

export interface MidpointDecision {
  prompt: string;
  options: MidpointOption[];
}

export interface ActivityTypeConfig {
  id: string;
  first_half_min_seconds: number;
  first_half_max_seconds: number;
  second_half_min_seconds: number;
  second_half_max_seconds: number;
  midpoint_decision: MidpointDecision;
}

export interface TrainingCycleInit {
  state: "running_first_half";
  first_half_seconds: number;
  transition_at: string; // ISO 8601
}

// Runtime-loaded config (populated by loadTrainingActivityTypes at startup)
let activityTypes: ReadonlyMap<string, ActivityTypeConfig> = new Map();

export function getActivityTypeConfig(id: string): ActivityTypeConfig | undefined {
  return activityTypes.get(id);
}

export function setTrainingActivityTypes(map: ReadonlyMap<string, ActivityTypeConfig>): void {
  activityTypes = map;
}

function requireNumber(obj: Record<string, unknown>, key: string, rowId: string): number {
  const v = obj[key];
  if (typeof v !== "number") {
    throw new Error(`training_activity_types[${rowId}].${key} is not a number: ${String(v)}`);
  }
  return v;
}

function requireString(obj: Record<string, unknown>, key: string, context: string): string {
  const v = obj[key];
  if (typeof v !== "string") {
    throw new Error(`${context}.${key} is not a string: ${String(v)}`);
  }
  return v;
}

/** Parse a raw JSONB row from training_activity_types.data into the typed config. */
function parseActivityTypeRow(id: string, raw: unknown): ActivityTypeConfig {
  if (!raw || typeof raw !== "object") {
    throw new Error(`training_activity_types[${id}].data is not an object`);
  }
  const data = raw as Record<string, unknown>;
  const decisionRaw = data.midpoint_decision;
  if (!decisionRaw || typeof decisionRaw !== "object") {
    throw new Error(`training_activity_types[${id}].midpoint_decision is missing`);
  }
  const decision = decisionRaw as Record<string, unknown>;
  const rawOptions = decision.options;
  if (!Array.isArray(rawOptions)) {
    throw new Error(`training_activity_types[${id}].midpoint_decision.options is not an array`);
  }
  const options = rawOptions.map((raw, i) => {
    const o = raw as Record<string, unknown>;
    const ctx = `training_activity_types[${id}].midpoint_decision.options[${i}]`;
    return {
      id: requireString(o, "id", ctx),
      label: requireString(o, "label", ctx),
    };
  });
  return {
    id,
    first_half_min_seconds: requireNumber(data, "first_half_min_seconds", id),
    first_half_max_seconds: requireNumber(data, "first_half_max_seconds", id),
    second_half_min_seconds: requireNumber(data, "second_half_min_seconds", id),
    second_half_max_seconds: requireNumber(data, "second_half_max_seconds", id),
    midpoint_decision: {
      prompt: requireString(decision, "prompt", `training_activity_types[${id}].midpoint_decision`),
      options,
    },
  };
}

export async function loadTrainingActivityTypes(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM training_activity_types
  `;
  const map = new Map<string, ActivityTypeConfig>();
  for (const row of rows) {
    map.set(row.id, parseActivityTypeRow(row.id, row.data));
  }
  activityTypes = map;
  console.log(`Loaded ${map.size} training activity types`);
}

export function getMidpointDecision(activityType: string): MidpointDecision {
  const config = activityTypes.get(activityType);
  if (!config) {
    throw new Error(`Unknown training activity type: ${activityType}`);
  }
  return config.midpoint_decision;
}

export function startTrainingCycle(activityType: string, startTime: Date): TrainingCycleInit {
  const config = activityTypes.get(activityType);
  if (!config) {
    throw new Error(`Unknown training activity type: ${activityType}`);
  }

  const firstHalf =
    Math.floor(
      Math.random() * (config.first_half_max_seconds - config.first_half_min_seconds + 1),
    ) + config.first_half_min_seconds;
  const transitionAt = new Date(startTime.getTime() + firstHalf * 1000);

  return {
    state: "running_first_half",
    first_half_seconds: firstHalf,
    transition_at: transitionAt.toISOString(),
  };
}
