import { describe, expect, test } from "bun:test";
import { ERRAND_TEMPLATES } from "./activity_templates.ts";

// Durations must match the spec's Errand Types table
// (docs/game_mechanics/game_mechanics_core.md L824-829), expressed in seconds.
describe("ERRAND_TEMPLATES durations match spec", () => {
  const HOUR = 3600;
  const expected: Record<string, { min: number; max: number }> = {
    scout: { min: 4 * HOUR, max: 8 * HOUR }, // 4-8 hrs
    social: { min: 3 * HOUR, max: 6 * HOUR }, // 3-6 hrs
    acquire: { min: 4 * HOUR, max: 10 * HOUR }, // 4-10 hrs
    relationship: { min: 2 * HOUR, max: 4 * HOUR }, // 2-4 hrs
  };

  for (const [type, { min, max }] of Object.entries(expected)) {
    test(`${type} duration is ${min / HOUR}-${max / HOUR}h`, () => {
      const template = ERRAND_TEMPLATES[type];
      expect(template).toBeDefined();
      expect(template!.duration_min_seconds).toBe(min);
      expect(template!.duration_max_seconds).toBe(max);
    });
  }
});
