import { describe, expect, test, beforeEach } from "bun:test";
import {
  validateErrandDispatch,
  numericToDangerLevel,
  setDestinationDangerLevels,
  loadDestinationDangerLevels,
  getDangerLevel,
  BLOCKED_DANGER_COMBOS,
} from "./errand_risk.ts";
import { setLocations } from "./locations.ts";
import type { Location, LocationCondition } from "@divineruin/shared";
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

describe("loadDestinationDangerLevels — derives bands from loaded locations", () => {
  // The danger map is no longer its own SQL read; it is derived from the locations
  // loaded by locations.ts (listLocations()), so locations are the single SQL source.
  function loc(id: string, danger_level?: number): Location {
    const base: Location = {
      id,
      name: id,
      tier: 1,
      district: "d",
      region: "r",
      atmosphere: "a",
      tags: [],
      exits: {},
    };
    if (danger_level !== undefined) base.danger_level = danger_level;
    return base;
  }

  test("maps each location's numeric danger_level to its band; missing -> safe", () => {
    setLocations(
      new Map<string, Location>([
        ["safe_place", loc("safe_place", 0)],
        ["risky", loc("risky", 2)],
        ["unmarked", loc("unmarked")],
      ]),
    );
    loadDestinationDangerLevels();
    expect(getDangerLevel("safe_place")).toBe("safe");
    expect(getDangerLevel("risky")).toBe("dangerous");
    expect(getDangerLevel("unmarked")).toBe("safe");
    setLocations(new Map());
  });
});

describe("BLOCKED_DANGER_COMBOS conformance", () => {
  // game_mechanics_core.md §Companion Risk L887-892 marks these cells N/A. Risk
  // is now rolled in the Python worker (ADR 0006); the risk table moved to
  // apps/agent/errand_risk.py with its own conformance pin. TS keeps only this
  // dispatch-time blocked-combo gate, conformance-pinned to the same spec.
  //
  // This literal is the spec REGRESSION PIN (the markdown table is the human
  // oracle). Cross-language drift between this Set and the Python frozenset is
  // separately guarded by apps/agent/tests/test_errand_risk_conformance.py, which
  // parses this source and asserts py == ts — so the two pins cannot silently
  // diverge from each other.
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

describe("per-condition danger overrides vs the static gate (concern 30b8d7c984c0)", () => {
  // loadDestinationDangerLevels derives the band map from each location's TOP-LEVEL
  // danger_level only; validateErrandDispatch is stateless (no world-state arg) so it
  // cannot apply per-condition overrides (Location.conditions[*].danger_level /
  // danger_level_add) at dispatch time. This guard makes that blind spot EXPLICIT: it
  // recomputes each condition's effective band and asserts no condition introduces a
  // BLOCKED_DANGER_COMBOS entry the top-level band misses — EXCEPT the known, accepted
  // gaps below. A NEW silent gap (new content, or drift in the known one) fails this test.
  //
  // KNOWN, ACCEPTED gap: greyvale_ruins_entrance is dangerous (2) baseline; under
  // hollow_corruption >= 3 its danger_level_add:2 pushes it to extreme, which blocks
  // social/acquire/relationship the static "dangerous" band allows. Accepted because the
  // gate is stateless by design and statically over-blocking would nerf baseline-condition
  // gameplay; the proper fix is a world-state-aware dispatch gate (tracked as debt).
  const KNOWN_CONDITION_DANGER_GAPS = new Set(["greyvale_ruins_entrance"]);
  const ERRAND_TYPES = ["scout", "social", "acquire", "relationship"] as const;
  const CONTENT_PATH = new URL("../../../content/locations.json", import.meta.url);

  // Use the shared Location/LocationCondition types (which model danger_level and
  // danger_level_add) so a new danger field on either is tracked here, not silently
  // dropped by a private inline shape.
  const clampBand = (n: number): number => Math.max(0, Math.min(3, n));

  test("no per-condition danger override silently widens BLOCKED_DANGER_COMBOS beyond the known gaps", async () => {
    const raw: unknown = await Bun.file(CONTENT_PATH).json();
    if (!Array.isArray(raw)) throw new Error("content/locations.json is not an array");
    const locations = raw as Location[];

    const gaps = new Set<string>();
    for (const loc of locations) {
      const topNum = loc.danger_level ?? 0;
      // Clamp the top-level band symmetrically with the condition path: parseLocationRow
      // only range-checks integers loosely, so content could carry a top-level danger_level
      // outside 0-3, which numericToDangerLevel throws on. Clamping keeps the guard from an
      // opaque throw while still flagging real band widening.
      const topBand = numericToDangerLevel(clampBand(topNum));
      for (const cond of Object.values<LocationCondition>(loc.conditions ?? {})) {
        let effNum: number | undefined;
        if (cond.danger_level !== undefined) effNum = cond.danger_level;
        else if (cond.danger_level_add !== undefined) effNum = topNum + cond.danger_level_add;
        if (effNum === undefined) continue;

        const effBand = numericToDangerLevel(clampBand(effNum));
        const introducesNewBlock = ERRAND_TYPES.some(
          (e) =>
            BLOCKED_DANGER_COMBOS.has(`${effBand}|${e}`) &&
            !BLOCKED_DANGER_COMBOS.has(`${topBand}|${e}`),
        );
        if (introducesNewBlock) gaps.add(loc.id);
      }
    }

    // Equality (not subset): catches BOTH a new silent gap AND drift in the known one
    // (e.g. greyvale's override removed -> update the allowlist).
    expect(gaps).toEqual(KNOWN_CONDITION_DANGER_GAPS);
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
