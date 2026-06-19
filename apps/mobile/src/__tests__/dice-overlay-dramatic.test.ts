import { test, expect, describe } from "bun:test";

import { isDramaticDicePayload } from "@/utils/dice-overlay-dramatic";

// Unit-testable dramatic-gate logic (story-006, M4.5). Lives in a .ts (not the
// dice-roll-overlay .tsx) so the bun suite can import it without react-native — the RN
// mock omits View/Text, so a .tsx import throws at module load (mirrors spell-display.ts).
// The overlay gates its tumble-and-reveal on this; scarcity is the point — only a roll
// the agent explicitly flagged dramatic earns the full animation.

describe("isDramaticDicePayload", () => {
  test("dramatic: true returns true (full reveal presentation)", () => {
    expect(isDramaticDicePayload({ dramatic: true })).toBe(true);
  });

  test("dramatic: false suppresses (returns false)", () => {
    expect(isDramaticDicePayload({ dramatic: false })).toBe(false);
  });

  test("absent dramatic field suppresses (scarcity-pure default)", () => {
    expect(isDramaticDicePayload({ roll: 18, total: 20 })).toBe(false);
    expect(isDramaticDicePayload({})).toBe(false);
  });

  test("a non-boolean dramatic value suppresses (defensive)", () => {
    expect(isDramaticDicePayload({ dramatic: "true" })).toBe(false);
    expect(isDramaticDicePayload({ dramatic: 1 })).toBe(false);
    expect(isDramaticDicePayload({ dramatic: null })).toBe(false);
    expect(isDramaticDicePayload({ dramatic: undefined })).toBe(false);
  });

  test("the gate ignores the resonance-band signal entirely", () => {
    // The Hollow-Echo band lives on a separate event/overlay; it must never sway the
    // dramatic gate. A band present without dramatic:true stays suppressed.
    expect(isDramaticDicePayload({ band: "shattered" })).toBe(false);
    expect(isDramaticDicePayload({ band: "shattered", dramatic: true })).toBe(true);
  });
});
