import { describe, expect, test } from "bun:test";
import {
  rollErrandRisk,
  validateErrandDispatch,
  DESTINATION_DANGER_LEVELS,
  type InjuryStatus,
} from "./errand_risk.ts";

describe("DESTINATION_DANGER_LEVELS", () => {
  test("millhaven is safe", () => {
    expect(DESTINATION_DANGER_LEVELS["millhaven"]).toBe("safe");
  });

  test("greyvale_ruins_entrance is dangerous", () => {
    expect(DESTINATION_DANGER_LEVELS["greyvale_ruins_entrance"]).toBe("dangerous");
  });

  test("accord_market_square is moderate", () => {
    expect(DESTINATION_DANGER_LEVELS["accord_market_square"]).toBe("moderate");
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
