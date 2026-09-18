/**
 * Shared test fixture for training configuration.
 *
 * Loads content/training_activity_types.json and content/training_programs.json
 * directly at test setup time, then populates the runtime maps. Keeping the
 * fixture file-driven avoids drift between the content JSON and test data.
 */

import {
  parseActivityTypeRows,
  setTrainingActivityTypes,
  type ActivityTypeConfig,
} from "../training_state_machine.ts";
import { setTrainingPrograms, type TrainingProgramConfig } from "../activity_templates.ts";

const ACTIVITY_TYPES_PATH = new URL(
  "../../../../content/training_activity_types.json",
  import.meta.url,
);
const PROGRAMS_PATH = new URL("../../../../content/training_programs.json", import.meta.url);

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

  const rawTypes = (await Bun.file(ACTIVITY_TYPES_PATH).json()) as Record<string, unknown>[];
  cachedActivityTypes = new Map(
    parseActivityTypeRows(rawTypes.map(({ id, ...data }) => ({ id: id as string, data }))),
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
