import { test, expect, describe } from "bun:test";
import type { Ability, Archetype, Milestone, RoleArchetype } from "@divineruin/shared";
import { handleGetContentCatalog } from "./content-catalog-api.ts";
import { setRoleArchetypes } from "./role_archetypes.ts";
import { setArchetypes } from "./archetypes.ts";
import { setAbilities } from "./abilities.ts";
import { setMilestones } from "./milestones.ts";

// The catalog endpoint is a thin in-memory read over each loader's map (no DB), so seeding
// id-only stubs via the set* seams is enough to pin dispatch + shape. Cross-language parse
// conformance is proven separately by the per-loader *-load tests + acceptance round-trips.
function seedCatalogs(): void {
  setRoleArchetypes(new Map([["smith", { id: "smith" } as RoleArchetype]]));
  setArchetypes(new Map([["warrior", { id: "warrior" } as Archetype]]));
  setAbilities(new Map([["cleave", { id: "cleave" } as Ability]]));
  setMilestones(new Map([["m_first_blood", { id: "m_first_blood" } as Milestone]]));
}

describe("handleGetContentCatalog", () => {
  test.each([
    ["role-archetypes", "smith"],
    ["archetypes", "warrior"],
    ["abilities", "cleave"],
    ["milestones", "m_first_blood"],
  ])("GET /api/content/%s returns the seeded catalog (200)", async (name, expectedId) => {
    seedCatalogs();
    const res = handleGetContentCatalog(name);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { catalog: string; items: { id: string }[] };
    expect(body.catalog).toBe(name);
    expect(body.items.map((i) => i.id)).toContain(expectedId);
  });

  test("unknown catalog returns 404 with an error body", async () => {
    const res = handleGetContentCatalog("nonexistent");
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error?: string };
    expect(body.error).toBeDefined();
  });

  // Inherited Object members ("constructor", "__proto__", "toString") must NOT resolve to a
  // catalog accessor — a plain-object registry would let these bypass the 404 guard.
  test.each(["constructor", "__proto__", "toString"])(
    "inherited member %s returns 404, not a leaked accessor",
    (name) => {
      expect(handleGetContentCatalog(name).status).toBe(404);
    },
  );
});
