import { test, expect, describe } from "bun:test";
import { startTrainingCycle, TRAINING_DURATION_CONFIG } from "./training_state_machine.ts";

describe("startTrainingCycle", () => {
  const now = new Date("2026-04-07T12:00:00Z");

  test("returns running_first_half state", () => {
    const result = startTrainingCycle("technique_base", now);
    expect(result.state).toBe("running_first_half");
  });

  test("transition_at equals startTime + first_half_seconds", () => {
    const result = startTrainingCycle("technique_base", now);
    const expected = new Date(now.getTime() + result.first_half_seconds * 1000);
    expect(result.transition_at).toBe(expected.toISOString());
  });

  test("first_half_seconds within range for technique_base", () => {
    const config = TRAINING_DURATION_CONFIG["technique_base"];
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("technique_base", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max);
    }
  });

  test("first_half_seconds within range for skill_practice", () => {
    const config = TRAINING_DURATION_CONFIG["skill_practice"];
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("skill_practice", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max);
    }
  });

  test("first_half_seconds within range for spell_standard", () => {
    const config = TRAINING_DURATION_CONFIG["spell_standard"];
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("spell_standard", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max);
    }
  });

  test("throws for unknown activity type", () => {
    expect(() => startTrainingCycle("unknown_type", now)).toThrow("Unknown training activity type");
  });
});
