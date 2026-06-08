import { test, expect, describe } from "bun:test";
import { getRoleArchetype, parseRoleArchetypeRow, setRoleArchetypes } from "./role_archetypes.ts";
import type { RoleArchetype } from "@divineruin/shared";

// Pins the fail-loud parseRoleArchetypeRow + accessors. The catalog-conformance pass over
// content/role_archetypes.json lives in role_archetypes-load.test.ts. parseRoleArchetypeRow
// is the cross-language twin of apps/agent/role_archetypes.py parse_role_archetype_row — the
// same malformed rows that the Python loader rejects (test_role_archetypes.py) reject here.

const ROOT = new URL("../../../", import.meta.url);
const ARCHETYPES_PATH = new URL("content/role_archetypes.json", ROOT);
const RAW = (await Bun.file(ARCHETYPES_PATH).json()) as Record<string, unknown>[];
const row = (id: string): Record<string, unknown> => ({ ...RAW.find((r) => r.id === id)! });

describe("parseRoleArchetypeRow — valid rows", () => {
  test("a combatant parses with combat_stats", () => {
    const guard = parseRoleArchetypeRow("guard", row("guard"));
    expect(guard.role_type).toBe("military");
    expect(guard.combat_stats).not.toBeNull();
    expect(guard.combat_stats?.hp).toBeTypeOf("number");
    expect(guard.combat_stats?.attributes.strength).toBeTypeOf("number");
  });

  test("a non-combatant parses with combat_stats null and services", () => {
    const inn = parseRoleArchetypeRow("innkeeper", row("innkeeper"));
    expect(inn.combat_stats).toBeNull();
    expect(inn.services.length).toBeGreaterThan(0);
    const firstService = inn.services[0];
    expect(firstService).toBeDefined();
    if (firstService) expect(["sp", "gp"]).toContain(firstService.cost_unit);
  });
});

describe("parseRoleArchetypeRow — fail-loud (parity with the Python loader)", () => {
  test("missing default_disposition", () => {
    const bad = row("guard");
    delete bad.default_disposition;
    expect(() => parseRoleArchetypeRow("guard", bad)).toThrow("guard");
  });

  test("wrong-typed price_modifier", () => {
    expect(() =>
      parseRoleArchetypeRow("blacksmith", { ...row("blacksmith"), price_modifier: "cheap" }),
    ).toThrow("price_modifier is not a number");
  });

  test("invalid role_type", () => {
    expect(() =>
      parseRoleArchetypeRow("guard", { ...row("guard"), role_type: "wizardly" }),
    ).toThrow("role_type");
  });

  test("invalid default_disposition", () => {
    expect(() =>
      parseRoleArchetypeRow("guard", { ...row("guard"), default_disposition: "ecstatic" }),
    ).toThrow("default_disposition");
  });

  test("malformed nested combat_stats", () => {
    expect(() =>
      parseRoleArchetypeRow("guard", { ...row("guard"), combat_stats: { hp: "lots", ac: 14 } }),
    ).toThrow("guard");
  });

  test("malformed service (bad cost_unit)", () => {
    const bad = row("innkeeper");
    bad.services = [{ name: "lodging", cost: 1, cost_unit: "credits" }];
    expect(() => parseRoleArchetypeRow("innkeeper", bad)).toThrow('cost_unit is not "sp" or "gp"');
  });

  test("malformed service ({min,max} cost with a non-number bound)", () => {
    const bad = row("innkeeper");
    bad.services = [{ name: "lodging", cost: { min: 5, max: "lots" }, cost_unit: "sp" }];
    expect(() => parseRoleArchetypeRow("innkeeper", bad)).toThrow("cost.max is not a number");
  });

  test("non-object row", () => {
    expect(() => parseRoleArchetypeRow("x", "nope")).toThrow("role_archetypes[x] is not an object");
  });
});

describe("accessors", () => {
  test("getRoleArchetype returns a set archetype, throws on unknown", () => {
    const guard = parseRoleArchetypeRow("guard", row("guard"));
    const map = new Map<string, RoleArchetype>([["guard", guard]]);
    setRoleArchetypes(map);
    expect(getRoleArchetype("guard").id).toBe("guard");
    expect(() => getRoleArchetype("nobody")).toThrow("Unknown role archetype: nobody");
  });
});
