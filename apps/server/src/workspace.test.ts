import { test, expect, describe } from "bun:test";

import { parseWorkspaceType, FIELD, type WorkspaceType } from "./workspace.ts";

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
    // A stray/typo'd workspace_type must not silently widen access.
    expect(() => parseWorkspaceType("kitchen", "workspace_rentals.workspace_type")).toThrow(
      /workspace_rentals\.workspace_type/,
    );
  });

  test.each([null, undefined, 7, {}])("fails loud on a non-string (%p)", (bad) => {
    expect(() => parseWorkspaceType(bad, "ctx")).toThrow();
  });
});
