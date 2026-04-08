/**
 * Shared test fixture for training configuration.
 *
 * Loads content/training_activity_types.json and content/training_programs.json
 * directly at test setup time, then populates the runtime maps. Keeping the
 * fixture file-driven avoids drift between the content JSON and test data.
 */

import { setTrainingActivityTypes, type ActivityTypeConfig } from "../training_state_machine.ts";
import { setTrainingPrograms, type TrainingProgramConfig } from "../activity_templates.ts";

const ACTIVITY_TYPES_PATH = new URL(
  "../../../../content/training_activity_types.json",
  import.meta.url,
);
const PROGRAMS_PATH = new URL("../../../../content/training_programs.json", import.meta.url);

interface RawActivityType {
  id: string;
  first_half_min_seconds: number;
  first_half_max_seconds: number;
  second_half_min_seconds: number;
  second_half_max_seconds: number;
  midpoint_decision: {
    prompt: string;
    options: { id: string; label: string }[];
  };
}

interface RawProgram {
  id: string;
  name: string;
  training_activity_type: TrainingProgramConfig["training_activity_type"];
  stat: string;
  skill?: string;
  dc: number;
  mentor_id: string;
}

let cachedActivityTypes: Map<string, ActivityTypeConfig> | null = null;
let cachedPrograms: Map<string, TrainingProgramConfig> | null = null;

async function loadFixtureData(): Promise<void> {
  if (cachedActivityTypes && cachedPrograms) return;

  const rawTypes = (await Bun.file(ACTIVITY_TYPES_PATH).json()) as RawActivityType[];
  cachedActivityTypes = new Map(
    rawTypes.map((t) => [
      t.id,
      {
        id: t.id,
        first_half_min_seconds: t.first_half_min_seconds,
        first_half_max_seconds: t.first_half_max_seconds,
        second_half_min_seconds: t.second_half_min_seconds,
        second_half_max_seconds: t.second_half_max_seconds,
        midpoint_decision: {
          prompt: t.midpoint_decision.prompt,
          options: t.midpoint_decision.options.map((o) => ({ id: o.id, label: o.label })),
        },
      },
    ]),
  );

  const rawPrograms = (await Bun.file(PROGRAMS_PATH).json()) as RawProgram[];
  cachedPrograms = new Map(rawPrograms.map((p) => [p.id, p]));
}

// Preload at module import so setupTrainingConfigFixture can stay sync
await loadFixtureData();

export function setupTrainingConfigFixture(): void {
  if (!cachedActivityTypes || !cachedPrograms) {
    throw new Error("Training fixture data not loaded");
  }
  setTrainingActivityTypes(cachedActivityTypes);
  setTrainingPrograms(cachedPrograms);
}
