import { describe, expect, test, beforeEach } from "bun:test";
import {
  rollErrandRisk,
  validateErrandDispatch,
  numericToDangerLevel,
  setDestinationDangerLevels,
  ERRAND_RISK_TABLE,
  BLOCKED_DANGER_COMBOS,
  type InjuryStatus,
} from "./errand_risk.ts";
import { setupDangerLevelFixture } from "./test-fixtures/danger-levels.ts";

beforeEach(() => {
  setupDangerLevelFixture();
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

describe("rollErrandRisk", () => {
  test("safe destination always returns none", () => {
    const results = new Set<InjuryStatus>();
    for (let i = 0; i < 100; i++) {
      results.add(rollErrandRisk("scout", "millhaven", "companion_kael"));
    }
    expect(results.size).toBe(1);
    expect(results.has("none")).toBe(true);
  });

  test("safe destination with any errand type returns none", () => {
    for (const errandType of ["scout", "social", "acquire", "relationship"] as const) {
      expect(rollErrandRisk(errandType, "millhaven", "companion_kael")).toBe("none");
    }
  });

  test("dangerous scout can produce injured or emergency", () => {
    const results = new Set<InjuryStatus>();
    for (let i = 0; i < 500; i++) {
      results.add(rollErrandRisk("scout", "greyvale_ruins_entrance", "companion_lira"));
    }
    // With 25% injury + 5% emergency (no reduction for lira), 500 rolls should hit all outcomes
    expect(results.has("none")).toBe(true);
    expect(results.has("injured")).toBe(true);
    expect(results.has("emergency")).toBe(true);
  });

  test("moderate scout can produce injured but not emergency", () => {
    // moderate/scout: 10% injury, 0% emergency
    const results = new Set<InjuryStatus>();
    for (let i = 0; i < 500; i++) {
      results.add(rollErrandRisk("scout", "accord_market_square", "companion_kael"));
    }
    expect(results.has("none")).toBe(true);
    expect(results.has("injured")).toBe(true);
    expect(results.has("emergency")).toBe(false);
  });

  test("companion_kael reduces injury chance by 5%", () => {
    // dangerous/scout base: 25% injury, 5% emergency
    // With kael (-5%): 20% injury, 5% emergency → 75% none
    // Without kael (lira, 0% reduction): 25% injury, 5% emergency → 70% none
    let kaelNoneCount = 0;
    let liraNoneCount = 0;
    const trials = 5000;

    for (let i = 0; i < trials; i++) {
      if (rollErrandRisk("scout", "greyvale_ruins_entrance", "companion_kael") === "none")
        kaelNoneCount++;
      if (rollErrandRisk("scout", "greyvale_ruins_entrance", "companion_lira") === "none")
        liraNoneCount++;
    }

    // Kael should have more "none" outcomes (higher none rate)
    const kaelNoneRate = kaelNoneCount / trials;
    const liraNoneRate = liraNoneCount / trials;
    expect(kaelNoneRate).toBeGreaterThan(liraNoneRate - 0.05);
    // Kael none rate should be around 75% (±5% for randomness)
    expect(kaelNoneRate).toBeGreaterThan(0.65);
    expect(kaelNoneRate).toBeLessThan(0.85);
  });

  test("unknown destination defaults to safe (returns none)", () => {
    expect(rollErrandRisk("scout", "unknown_place", "companion_kael")).toBe("none");
  });

  test("unknown companion gets no injury reduction", () => {
    // Should behave same as default
    const result = rollErrandRisk("scout", "millhaven", "unknown_companion");
    expect(result).toBe("none");
  });
});

describe("ERRAND_RISK_TABLE matches the spec matrix", () => {
  // game_mechanics_core.md §Companion Risk L887-892. Cells marked None are
  // explicit 0/0 entries; cells marked N/A are absent from the table and
  // enforced by BLOCKED_DANGER_COMBOS instead. Deterministic — pins exact
  // percentages, unlike statistical roll sampling.
  const specCells: Record<string, { injuryPct: number; emergencyPct: number }> = {
    "safe|scout": { injuryPct: 0, emergencyPct: 0 },
    "safe|social": { injuryPct: 0, emergencyPct: 0 },
    "safe|acquire": { injuryPct: 0, emergencyPct: 0 },
    "safe|relationship": { injuryPct: 0, emergencyPct: 0 },
    "moderate|scout": { injuryPct: 10, emergencyPct: 0 },
    "moderate|social": { injuryPct: 0, emergencyPct: 0 },
    "moderate|acquire": { injuryPct: 10, emergencyPct: 0 },
    "moderate|relationship": { injuryPct: 0, emergencyPct: 0 },
    "dangerous|scout": { injuryPct: 25, emergencyPct: 5 },
    "dangerous|social": { injuryPct: 0, emergencyPct: 0 },
    "dangerous|acquire": { injuryPct: 20, emergencyPct: 0 },
    "extreme|scout": { injuryPct: 40, emergencyPct: 15 },
  };

  test("every populated cell matches spec exactly", () => {
    for (const [key, entry] of Object.entries(specCells)) {
      expect(ERRAND_RISK_TABLE[key]).toEqual(entry);
    }
  });

  test("table has no cells beyond the spec (N/A cells stay absent)", () => {
    expect(new Set(Object.keys(ERRAND_RISK_TABLE))).toEqual(new Set(Object.keys(specCells)));
  });

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
