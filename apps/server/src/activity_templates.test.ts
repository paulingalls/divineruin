import { beforeEach, describe, expect, mock, test } from "bun:test";
import { dbMockFactory, resetMockDb } from "./activities-test-mock.ts";
import { setupErrandTemplatesFixture } from "./test-fixtures/errand-templates.ts";
import { setupTrainingConfigFixture } from "./test-fixtures/training-config.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleGetActivityTemplates } = await import("./activity-templates-api.ts");
const { getAllTrainingPrograms, getErrandTemplate } = await import("./activity_templates.ts");

beforeEach(() => {
  resetMockDb();
  setupErrandTemplatesFixture();
  setupTrainingConfigFixture();
});

test("training templates exclude programs the app cannot launch", async () => {
  const response = await handleGetActivityTemplates("player_1");
  const payload = (await response.json()) as {
    groups: { type: string; items: { id: string }[] }[];
  };
  const training = payload.groups.find((group) => group.type === "training");
  const expectedIds = getAllTrainingPrograms()
    .filter((program) => !program.training_activity_type.startsWith("spell_"))
    .map((program) => program.id);

  expect(training).toBeDefined();
  expect(training!.items.length).toBeGreaterThan(0);
  expect(training!.items.map((item) => item.id)).toEqual(expectedIds);
  expect(training!.items.map((item) => item.id)).toContain("combat_basics");
  expect(training!.items.map((item) => item.id)).not.toContain("arcane_study");
});

// Durations must match the spec's Errand Types table
// (docs/game_mechanics/game_mechanics_core.md L824-829), expressed in seconds.
// Templates are now DB-loaded from content/errand_templates.json; the fixture
// loads that same JSON, so this pins the shared source against the spec.
describe("errand template durations match spec", () => {
  const HOUR = 3600;
  const expected: Record<string, { min: number; max: number }> = {
    scout: { min: 4 * HOUR, max: 8 * HOUR }, // 4-8 hrs
    social: { min: 3 * HOUR, max: 6 * HOUR }, // 3-6 hrs
    acquire: { min: 4 * HOUR, max: 10 * HOUR }, // 4-10 hrs
    relationship: { min: 2 * HOUR, max: 4 * HOUR }, // 2-4 hrs
  };

  for (const [type, { min, max }] of Object.entries(expected)) {
    test(`${type} duration is ${min / HOUR}-${max / HOUR}h`, () => {
      const template = getErrandTemplate(type);
      expect(template).toBeDefined();
      expect(template!.duration_min_seconds).toBe(min);
      expect(template!.duration_max_seconds).toBe(max);
    });
  }
});
