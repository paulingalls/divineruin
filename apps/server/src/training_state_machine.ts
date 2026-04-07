/**
 * Training cycle state machine — first-half init only.
 *
 * Ports the start_training_cycle logic from Python training_rules.py.
 * The Python async worker handles midpoint and completion transitions;
 * the TS server only needs to create the initial state.
 *
 * Uses `transition_at` (not `decision_at`) to match db_training.py query convention.
 */

export type TrainingActivityType =
  | "spell_cantrip"
  | "spell_standard"
  | "spell_major"
  | "spell_supreme"
  | "recipe_study"
  | "technique_base"
  | "technique_mentor"
  | "skill_practice";

interface DurationRange {
  first_half_min: number; // seconds
  first_half_max: number;
}

export interface TrainingCycleInit {
  state: "running_first_half";
  first_half_seconds: number;
  transition_at: string; // ISO 8601
}

function h(hours: number): number {
  return hours * 3600;
}

// First-half duration ranges from Python TRAINING_ACTIVITY_CONFIG (training_rules.py).
// Only first-half is needed here; second-half is handled by the Python async worker.
export const TRAINING_DURATION_CONFIG: Record<TrainingActivityType, DurationRange> = {
  spell_cantrip: { first_half_min: h(3), first_half_max: h(5) },
  spell_standard: { first_half_min: h(4), first_half_max: h(6) },
  spell_major: { first_half_min: h(4), first_half_max: h(6) },
  spell_supreme: { first_half_min: h(5), first_half_max: h(8) },
  recipe_study: { first_half_min: h(3), first_half_max: h(5) },
  technique_base: { first_half_min: h(4), first_half_max: h(6) },
  technique_mentor: { first_half_min: h(5), first_half_max: h(7) },
  skill_practice: { first_half_min: h(3), first_half_max: h(5) },
};

export function startTrainingCycle(activityType: string, startTime: Date): TrainingCycleInit {
  if (!(activityType in TRAINING_DURATION_CONFIG)) {
    throw new Error(`Unknown training activity type: ${activityType}`);
  }
  const config = TRAINING_DURATION_CONFIG[activityType as TrainingActivityType];

  const firstHalf =
    Math.floor(Math.random() * (config.first_half_max - config.first_half_min + 1)) +
    config.first_half_min;
  const transitionAt = new Date(startTime.getTime() + firstHalf * 1000);

  return {
    state: "running_first_half",
    first_half_seconds: firstHalf,
    transition_at: transitionAt.toISOString(),
  };
}
