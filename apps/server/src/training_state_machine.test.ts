import { test, expect, describe, beforeEach } from "bun:test";
import {
  startTrainingCycle,
  getActivityTypeConfig,
  getMidpointDecision,
  setTrainingActivityTypes,
  type ActivityTypeConfig,
} from "./training_state_machine.ts";
import { setupTrainingConfigFixture } from "./test-fixtures/training-config.ts";

beforeEach(() => {
  setupTrainingConfigFixture();
});

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
    const config = getActivityTypeConfig("technique_base")!;
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("technique_base", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min_seconds);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max_seconds);
    }
  });

  test("first_half_seconds within range for skill_practice", () => {
    const config = getActivityTypeConfig("skill_practice")!;
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("skill_practice", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min_seconds);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max_seconds);
    }
  });

  test("first_half_seconds within range for spell_standard", () => {
    const config = getActivityTypeConfig("spell_standard")!;
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("spell_standard", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min_seconds);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max_seconds);
    }
  });

  test("first_half_seconds within range for spell_minor", () => {
    const config = getActivityTypeConfig("spell_minor")!;
    for (let i = 0; i < 20; i++) {
      const result = startTrainingCycle("spell_minor", now);
      expect(result.first_half_seconds).toBeGreaterThanOrEqual(config.first_half_min_seconds);
      expect(result.first_half_seconds).toBeLessThanOrEqual(config.first_half_max_seconds);
    }
  });

  test("throws for unknown activity type", () => {
    expect(() => startTrainingCycle("unknown_type", now)).toThrow("Unknown training activity type");
  });
});

describe("training config seam", () => {
  test("setTrainingActivityTypes populates the runtime map", () => {
    const fixture: ActivityTypeConfig = {
      id: "technique_base",
      first_half_min_seconds: 14400,
      first_half_max_seconds: 21600,
      second_half_min_seconds: 10800,
      second_half_max_seconds: 18000,
      midpoint_decision: {
        prompt: "test",
        options: [
          { id: "a", label: "A" },
          { id: "b", label: "B" },
        ],
      },
    };
    setTrainingActivityTypes(new Map([["technique_base", fixture]]));

    const result = getActivityTypeConfig("technique_base");
    expect(result?.first_half_min_seconds).toBe(14400);
    expect(result?.midpoint_decision.options).toHaveLength(2);
  });

  test("getActivityTypeConfig returns undefined for unknown types", () => {
    setTrainingActivityTypes(new Map());
    expect(getActivityTypeConfig("nonexistent")).toBeUndefined();
  });
});

describe("getMidpointDecision", () => {
  test("returns prompt and options for technique_base", () => {
    const decision = getMidpointDecision("technique_base");
    expect(decision.prompt).toBeTruthy();
    expect(decision.options).toHaveLength(2);
    expect(decision.options[0]!.id).toBe("aggressive");
    expect(decision.options[0]!.label).toBeTruthy();
    expect(decision.options[1]!.id).toBe("defensive");
  });

  test("returns prompt and options for skill_practice", () => {
    const decision = getMidpointDecision("skill_practice");
    expect(decision.options).toHaveLength(2);
    expect(decision.options[0]!.id).toBe("fundamentals");
    expect(decision.options[1]!.id).toBe("advanced");
  });

  test("returns prompt and options for spell_standard", () => {
    const decision = getMidpointDecision("spell_standard");
    expect(decision.options).toHaveLength(2);
    expect(decision.options[0]!.id).toBe("power");
    expect(decision.options[1]!.id).toBe("control");
  });

  test("returns prompt and options for spell_minor", () => {
    const decision = getMidpointDecision("spell_minor");
    expect(decision.prompt.length).toBeGreaterThan(0);
    expect(decision.options).toHaveLength(2);
    expect(decision.options[0]!.id).toBeTruthy();
    expect(decision.options[1]!.id).toBeTruthy();
  });

  test("all activity types have decisions", () => {
    const types = [
      "spell_cantrip",
      "spell_minor",
      "spell_standard",
      "spell_major",
      "spell_supreme",
      "recipe_study",
      "technique_base",
      "technique_mentor",
      "skill_practice",
    ];
    for (const type of types) {
      const decision = getMidpointDecision(type);
      expect(decision.prompt.length).toBeGreaterThan(0);
      expect(decision.options.length).toBe(2);
      for (const opt of decision.options) {
        expect(opt.id).toBeTruthy();
        expect(opt.label).toBeTruthy();
      }
    }
  });

  test("throws for unknown activity type", () => {
    expect(() => getMidpointDecision("unknown_type")).toThrow("Unknown training activity type");
  });
});
