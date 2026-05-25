import { test, expect, describe, mock, beforeEach } from "bun:test";

// Type-only import is erased at runtime, so it doesn't trigger db.ts before the mock.
import type { WorkspaceType } from "./workspace.ts";

// accessibleWorkspaceTier queries ./db.ts; mock it with a call-sequence helper
// (mirrors auth.test.ts). Each query shifts the next queued result off the list;
// the bound template values are captured so we can assert the read is keyed by
// player + location. parseWorkspaceType is pure and ignores the mock.
let mockCallHandler: (strings: TemplateStringsArray, ...values: unknown[]) => Promise<unknown[]>;
let lastQueryValues: unknown[] = [];

function setMockResults(...results: unknown[][]) {
  let callIndex = 0;
  mockCallHandler = (_strings, ...values) => {
    lastQueryValues = values;
    const result = results[callIndex] ?? [];
    callIndex++;
    return Promise.resolve(result);
  };
}

void mock.module("./db.ts", () => ({
  sql: Object.assign(
    (strings: TemplateStringsArray, ...values: unknown[]) => mockCallHandler(strings, ...values),
    { close: () => Promise.resolve() },
  ),
}));

const { parseWorkspaceType, accessibleWorkspaceTier, FIELD } = await import("./workspace.ts");

beforeEach(() => {
  setMockResults();
  lastQueryValues = [];
});

describe("parseWorkspaceType", () => {
  test("accepts the four valid workspace types", () => {
    const valid: WorkspaceType[] = ["field", "workshop", "forge", "laboratory"];
    for (const value of valid) {
      expect(parseWorkspaceType(value, "ctx")).toBe(value);
    }
  });

  test("FIELD is the canonical field value", () => {
    expect(FIELD).toBe("field");
  });

  test("fails loud on an out-of-enum string", () => {
    expect(() => parseWorkspaceType("kitchen", "workspace_rentals.workspace_type")).toThrow(
      /workspace_rentals\.workspace_type/,
    );
  });

  test.each([null, undefined, 7, {}])("fails loud on a non-string (%p)", (bad) => {
    expect(() => parseWorkspaceType(bad, "ctx")).toThrow();
  });
});

describe("accessibleWorkspaceTier", () => {
  test("no rentals → only the field floor", async () => {
    setMockResults([]);
    const tiers = await accessibleWorkspaceTier("player-1", "millhaven_square");
    expect(tiers).toEqual(new Set(["field"]));
  });

  test("an active rental adds its type; field stays present", async () => {
    setMockResults([{ workspace_type: "forge" }]);
    const tiers = await accessibleWorkspaceTier("player-1", "millhaven_square");
    expect(tiers).toEqual(new Set(["field", "forge"]));
  });

  test("multiple rentals dedup into the set", async () => {
    setMockResults([
      { workspace_type: "workshop" },
      { workspace_type: "forge" },
      { workspace_type: "workshop" },
    ]);
    const tiers = await accessibleWorkspaceTier("player-1", "ashmark_city");
    expect(tiers).toEqual(new Set(["field", "workshop", "forge"]));
  });

  test("a bad workspace_type row fails loud (does not silently drop)", async () => {
    setMockResults([{ workspace_type: "kitchen" }]);
    let caught: unknown;
    try {
      await accessibleWorkspaceTier("player-1", "ashmark_city");
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toMatch(/workspace_rentals\.workspace_type/);
  });

  test("the read is parameterized by player and location", async () => {
    setMockResults([]);
    await accessibleWorkspaceTier("player-42", "greyvale_hamlet");
    // expires_at > NOW() filtering happens in SQL, so the mock can't exercise it
    // (proven in the real-DB acceptance lane, ADR 0003). Here we prove the query
    // is bound to the right player + location, not a global read.
    expect(lastQueryValues).toContain("player-42");
    expect(lastQueryValues).toContain("greyvale_hamlet");
  });
});
