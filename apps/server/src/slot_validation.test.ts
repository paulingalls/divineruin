import { describe, expect, test } from "bun:test";
import { activityTypeToSlot, validateSlotAvailability } from "./slot_validation.ts";

describe("activityTypeToSlot", () => {
  test("maps crafting to crafting slot", () => {
    expect(activityTypeToSlot("crafting")).toBe("crafting");
  });

  test("maps companion_errand to companion slot", () => {
    expect(activityTypeToSlot("companion_errand")).toBe("companion");
  });

  test("maps training to training slot", () => {
    expect(activityTypeToSlot("training")).toBe("training");
  });

  test("returns null for unknown type", () => {
    expect(activityTypeToSlot("unknown")).toBeNull();
  });
});

describe("validateSlotAvailability", () => {
  test("allows crafting when crafting slot is empty", () => {
    const result = validateSlotAvailability({ training: 0, crafting: 0, companion: 0 }, "crafting");
    expect(result).toEqual({ valid: true, error: null });
  });

  test("allows companion_errand when companion slot is empty", () => {
    const result = validateSlotAvailability(
      { training: 0, crafting: 0, companion: 0 },
      "companion_errand",
    );
    expect(result).toEqual({ valid: true, error: null });
  });

  test("allows training when training slot is empty", () => {
    const result = validateSlotAvailability({ training: 0, crafting: 0, companion: 0 }, "training");
    expect(result).toEqual({ valid: true, error: null });
  });

  test("allows different slots to be active simultaneously", () => {
    const slots = { training: 1, crafting: 1, companion: 0 };
    const result = validateSlotAvailability(slots, "companion_errand");
    expect(result).toEqual({ valid: true, error: null });
  });

  test("rejects crafting when crafting slot is full", () => {
    const result = validateSlotAvailability({ training: 0, crafting: 1, companion: 0 }, "crafting");
    expect(result).toEqual({ valid: false, error: "Crafting slot is full" });
  });

  test("rejects training when training slot is full", () => {
    const result = validateSlotAvailability({ training: 1, crafting: 0, companion: 0 }, "training");
    expect(result).toEqual({ valid: false, error: "Training slot is full" });
  });

  test("rejects companion_errand when companion slot is full", () => {
    const result = validateSlotAvailability(
      { training: 0, crafting: 0, companion: 1 },
      "companion_errand",
    );
    expect(result).toEqual({ valid: false, error: "Companion slot is full" });
  });

  test("rejects unknown activity type", () => {
    const result = validateSlotAvailability({ training: 0, crafting: 0, companion: 0 }, "unknown");
    expect(result).toEqual({ valid: false, error: "Invalid activity type: unknown" });
  });

  // Artificer exception tests
  test("Artificer with portable_lab can craft when crafting slot full but training slot empty", () => {
    const result = validateSlotAvailability(
      { training: 0, crafting: 1, companion: 0 },
      "crafting",
      "artificer",
      true,
    );
    expect(result).toEqual({ valid: true, error: null });
  });

  test("Artificer without portable_lab cannot craft when crafting slot full", () => {
    const result = validateSlotAvailability(
      { training: 0, crafting: 1, companion: 0 },
      "crafting",
      "artificer",
      false,
    );
    expect(result).toEqual({ valid: false, error: "Crafting slot is full" });
  });

  test("Artificer with portable_lab cannot craft when both crafting and training slots full", () => {
    const result = validateSlotAvailability(
      { training: 1, crafting: 1, companion: 0 },
      "crafting",
      "artificer",
      true,
    );
    expect(result).toEqual({ valid: false, error: "Both crafting and training slots are full" });
  });

  test("non-Artificer cannot use Artificer exception", () => {
    const result = validateSlotAvailability(
      { training: 0, crafting: 1, companion: 0 },
      "crafting",
      "warrior",
      true,
    );
    expect(result).toEqual({ valid: false, error: "Crafting slot is full" });
  });
});
