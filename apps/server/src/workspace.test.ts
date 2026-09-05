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

  // The Python bundle rental (crafting_tools._rent_workspace_impl) persists Forge +
  // Laboratory as TWO rows, never one bundle-token row. This vocabulary stays closed:
  // "forge_laboratory" is a rental OFFER token, never a stored workspace_type.
  test.each(["combined", "forge_laboratory"])(
    "the bundle token %p is not a workspace type",
    (bad) => {
      expect(() => parseWorkspaceType(bad, "workspace_rentals.workspace_type")).toThrow(
        /workspace_rentals\.workspace_type/,
      );
    },
  );
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

  // story-006: a Portable Lab grants Workshop + basic Laboratory anywhere (it does
  // NOT grant Forge), independent of location-bound rentals.
  test("a Portable Lab grants workshop + laboratory (not forge)", async () => {
    setMockResults([]);
    const tiers = await accessibleWorkspaceTier("player-1", "anywhere", { hasPortableLab: true });
    expect(tiers).toEqual(new Set(["field", "workshop", "laboratory"]));
  });

  test("hasPortableLab false / omitted leaves access rental-only", async () => {
    setMockResults([]);
    expect(
      await accessibleWorkspaceTier("player-1", "anywhere", { hasPortableLab: false }),
    ).toEqual(new Set(["field"]));
    setMockResults([]);
    expect(await accessibleWorkspaceTier("player-1", "anywhere")).toEqual(new Set(["field"]));
  });

  test("a bundle rental's two rows grant forge AND laboratory", async () => {
    setMockResults([{ workspace_type: "forge" }, { workspace_type: "laboratory" }]);
    expect(await accessibleWorkspaceTier("player-1", "accord_forge")).toEqual(
      new Set(["field", "forge", "laboratory"]),
    );
  });

  // Fault injection for the two-row decision: if the bundle ever persisted as ONE row
  // under its own token, every later crafting gate for this player hard-fails here.
  test.each(["combined", "forge_laboratory"])(
    "a single %p bundle row fails loud rather than widening access",
    async (bad) => {
      setMockResults([{ workspace_type: bad }]);
      let caught: unknown;
      try {
        await accessibleWorkspaceTier("player-1", "accord_forge");
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(Error);
      expect((caught as Error).message).toMatch(/workspace_rentals\.workspace_type/);
    },
  );

  test("the Portable Lab grant merges with active rentals", async () => {
    setMockResults([{ workspace_type: "forge" }]);
    const tiers = await accessibleWorkspaceTier("player-1", "ashmark_city", {
      hasPortableLab: true,
    });
    expect(tiers).toEqual(new Set(["field", "forge", "workshop", "laboratory"]));
  });
});
