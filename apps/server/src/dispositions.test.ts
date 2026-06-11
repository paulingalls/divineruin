import { test, expect, describe } from "bun:test";
import { DISPOSITION_ORDER } from "./dispositions.ts";

// The server runtime ladder (dispositions.ts) is hand-mirrored from the shared
// package's DISPOSITION_VALUES type SSOT — the shared barrel is type-only, so the
// runtime array cannot be imported across the package boundary. This pins the
// canonical literal here; the shared package's role_archetype.test.ts pins the same
// literal against DISPOSITION_VALUES. Two pins to one literal make drift between the
// server array and the type SSOT impossible without a test going red — the
// cross-package twin of the Python guard (test_story_005 asserts the ladder ==
// role_archetypes.DISPOSITIONS).

const CANONICAL_LADDER = ["hostile", "unfriendly", "neutral", "friendly", "trusted"];

describe("DISPOSITION_ORDER — server runtime SSOT", () => {
  test("is the canonical 5-tier ladder low->high", () => {
    expect(DISPOSITION_ORDER).toEqual(CANONICAL_LADDER);
  });
});
