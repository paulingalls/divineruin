import { describe, expect, test, beforeEach } from "bun:test";
import {
  validateErrandDispatch,
  numericToDangerLevel,
  setDestinationDangerLevels,
  BLOCKED_DANGER_COMBOS,
} from "./errand_risk.ts";
import { setupDangerLevelFixture } from "./test-fixtures/danger-levels.ts";
import { setupErrandTemplatesFixture } from "./test-fixtures/errand-templates.ts";

beforeEach(() => {
  setupDangerLevelFixture();
  setupErrandTemplatesFixture();
});

describe("numericToDangerLevel", () => {
  test("converts numeric strings to danger levels", () => {
    expect(numericToDangerLevel("0")).toBe("safe");
    expect(numericToDangerLevel("1")).toBe("moderate");
    expect(numericToDangerLevel("2")).toBe("dangerous");
    expect(numericToDangerLevel("3")).toBe("extreme");
  });

  test("null and undefined default to safe", () => {
    expect(numericToDangerLevel(null)).toBe("safe");
    expect(numericToDangerLevel(undefined)).toBe("safe");
  });

  test("unknown values throw", () => {
    expect(() => numericToDangerLevel("99")).toThrow("unknown danger_level value 99");
    expect(() => numericToDangerLevel("garbage")).toThrow("unknown danger_level value garbage");
  });

  test("accepts numeric input", () => {
    expect(numericToDangerLevel(2)).toBe("dangerous");
  });
});

describe("BLOCKED_DANGER_COMBOS conformance", () => {
  // game_mechanics_core.md §Companion Risk L887-892 marks these cells N/A. Risk
  // is now rolled in the Python worker (ADR 0006); the risk table moved to
  // apps/agent/errand_risk.py with its own conformance pin. TS keeps only this
  // dispatch-time blocked-combo gate, conformance-pinned to the same spec.
  test("BLOCKED_DANGER_COMBOS equals the spec N/A cells", () => {
    expect(BLOCKED_DANGER_COMBOS).toEqual(
      new Set([
        "dangerous|relationship",
        "extreme|relationship",
        "extreme|social",
        "extreme|acquire",
      ]),
    );
  });
});

describe("validateErrandDispatch", () => {
  test("valid combo returns valid", () => {
    const result = validateErrandDispatch("scout", "accord_market_square", "companion_kael");
    expect(result.valid).toBe(true);
    expect(result.error).toBeNull();
  });

  test("unknown destination is invalid", () => {
    const result = validateErrandDispatch("scout", "nowhere_land", "companion_kael");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("nowhere_land");
  });

  test("relationship errand at dangerous destination is blocked", () => {
    const result = validateErrandDispatch(
      "relationship",
      "greyvale_ruins_entrance",
      "companion_kael",
    );
    expect(result.valid).toBe(false);
    expect(result.error).toContain("relationship");
    expect(result.error).toContain("dangerous");
  });

  test("extreme destinations block social, acquire, and relationship (spec N/A cells)", () => {
    // Content has no danger_level=3 location yet, but the spec (L892) marks
    // social/acquire/relationship as N/A at extreme; pin BLOCKED_DANGER_COMBOS
    // against a synthetic extreme destination. Scout remains allowed.
    setDestinationDangerLevels(new Map([["deep_hollow", "extreme"]]));
    for (const errandType of ["social", "acquire", "relationship"]) {
      const result = validateErrandDispatch(errandType, "deep_hollow", "companion_kael");
      expect(result.valid).toBe(false);
      expect(result.error).toContain("extreme");
    }
    expect(validateErrandDispatch("scout", "deep_hollow", "companion_kael").valid).toBe(true);
  });

  test("companion_sable cannot perform social errands", () => {
    const result = validateErrandDispatch("social", "millhaven", "companion_sable");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("companion_sable");
    expect(result.error).toContain("social");
  });

  test("companion_sable cannot perform relationship errands", () => {
    const result = validateErrandDispatch("relationship", "millhaven", "companion_sable");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("companion_sable");
  });

  test("companion_kael can perform social errands at safe destinations", () => {
    const result = validateErrandDispatch("social", "millhaven", "companion_kael");
    expect(result.valid).toBe(true);
  });

  test("scout is allowed at all danger levels including dangerous", () => {
    const result = validateErrandDispatch("scout", "greyvale_ruins_entrance", "companion_kael");
    expect(result.valid).toBe(true);
  });

  test("dangerous|acquire is allowed (only relationship is blocked at dangerous)", () => {
    const result = validateErrandDispatch("acquire", "greyvale_ruins_entrance", "companion_kael");
    expect(result.valid).toBe(true);
  });

  test("unknown destination short-circuits before companion check", () => {
    // companion_sable would also fail social, but unknown destination should win
    const result = validateErrandDispatch("social", "nowhere_land", "companion_sable");
    expect(result.error).toContain("nowhere_land");
  });
});
