import { test, expect, describe, afterAll } from "bun:test";
import {
  parseMilestoneRow,
  getMilestone,
  getArchetypeMilestones,
  setMilestones,
} from "./milestones.ts";
import type { Milestone } from "@divineruin/shared";

// Drives the production fail-loud parseMilestoneRow (apps/server/src/milestones.ts)
// over content/archetype_milestones.json, proving every entry conforms to the shared
// Milestone contract. parseMilestoneRow is the real TS load boundary (loadMilestones calls
// it at startup); this test exercises it against the canonical content, pins its fail-loud
// behavior on malformed rows, and mirrors the Python loader's vocab/level assertions
// (apps/agent/milestones.py) so the cross-language contract is enforced on both sides.
// Records are self-contained (decision 4c0677dae1be): grants embed name/effect/flag.

const MILESTONES_PATH = new URL("../../../content/archetype_milestones.json", import.meta.url);

// content/archetype_milestones.json is a closed set (story-001): 72 milestones = 18
// archetypes x 4 tiers (L5/10/15/20). Exact counts catch both silent attrition from bad
// merges AND accidental additions (move these literals if story-001's content changes).
const MILESTONE_COUNT = 72;
const ARCHETYPE_COUNT = 18;

async function loadMilestonesJson(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(MILESTONES_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/archetype_milestones.json is not an array");
  return raw as Record<string, unknown>[];
}

describe("content/archetype_milestones.json — parseMilestoneRow conformance", () => {
  test(`exactly ${MILESTONE_COUNT} entries, each parses via the production parseMilestoneRow loader`, async () => {
    const rows = await loadMilestonesJson();
    expect(rows).toHaveLength(MILESTONE_COUNT);
    for (const row of rows) {
      const id = typeof row.id === "string" ? row.id : "<no-id>";
      // Throws with the milestone id + field context on any malformed entry.
      expect(() => parseMilestoneRow(id, row)).not.toThrow();
    }
  });

  test("a specialization-fork row round-trips its 2 options and null grant", async () => {
    const rows = await loadMilestonesJson();
    const fork = rows.find((r) => r.id === "warrior_identity");
    expect(fork).toBeDefined();
    const parsed = parseMilestoneRow("warrior_identity", fork!);
    expect(parsed.archetype_id).toBe("warrior");
    expect(parsed.tier).toBe("identity");
    expect(parsed.level).toBe(5);
    expect(parsed.kind).toBe("specialization_fork");
    expect(parsed.patron_deferred).toBe(false);
    expect(parsed.specialization_options).toHaveLength(2);
    expect(parsed.grant).toBeNull();
  });

  test("an auto-grant row carries its grant + extra_attack flag at L10", async () => {
    const rows = await loadMilestonesJson();
    const power = rows.find((r) => r.id === "warrior_power");
    expect(power).toBeDefined();
    const parsed = parseMilestoneRow("warrior_power", power!);
    expect(parsed.kind).toBe("auto_grant");
    expect(parsed.specialization_options).toHaveLength(0);
    expect(parsed.grant?.flag).toBe("extra_attack");
  });

  test("a patron-deferred L5 stub has no options and a null grant", async () => {
    const rows = await loadMilestonesJson();
    const cleric = rows.find((r) => r.id === "cleric_identity");
    expect(cleric).toBeDefined();
    const parsed = parseMilestoneRow("cleric_identity", cleric!);
    expect(parsed.patron_deferred).toBe(true);
    expect(parsed.specialization_options).toHaveLength(0);
    expect(parsed.grant).toBeNull();
  });
});

describe("milestones accessors — loadMilestones consumer chain", () => {
  // loadMilestones() reads the DB; its accessor chain (setMilestones ->
  // getMilestone/getArchetypeMilestones) is the runtime API consumers use after startup.
  // Drive it against the real parsed content (parseMilestoneRow per row, exactly as
  // loadMilestones does) without a live DB.
  async function loadParsedMap(): Promise<Map<string, Milestone>> {
    const rows = await loadMilestonesJson();
    const map = new Map<string, Milestone>();
    for (const row of rows) map.set(row.id as string, parseMilestoneRow(row.id as string, row));
    return map;
  }

  // milestones.ts is a process-shared cached module in Bun. Restore the default empty
  // registry so later tests see startup state, not this catalog.
  afterAll(() => setMilestones(new Map()));

  test("getArchetypeMilestones returns all 4 tiers for all 18 archetypes", async () => {
    const map = await loadParsedMap();
    setMilestones(map);
    const archetypeIds = new Set(Array.from(map.values()).map((m) => m.archetype_id));
    expect(archetypeIds.size).toBe(ARCHETYPE_COUNT);
    for (const id of archetypeIds) {
      const levels = getArchetypeMilestones(id)
        .map((m) => m.level)
        .sort((a, b) => a - b);
      expect(levels, `${id} milestone tiers`).toEqual([5, 10, 15, 20]);
    }
  });

  test("getMilestone returns a loaded milestone by id", async () => {
    setMilestones(await loadParsedMap());
    const fork = getMilestone("oracle_identity");
    expect(fork.archetype_id).toBe("oracle");
    expect(fork.patron_deferred).toBe(false);
    expect(fork.specialization_options).toHaveLength(2);
  });

  test("getMilestone is fail-loud on an unknown id", async () => {
    setMilestones(await loadParsedMap());
    expect(() => getMilestone("no_such_milestone_xyz")).toThrow(/no_such_milestone_xyz/);
  });

  test("getArchetypeMilestones returns an empty list for an unknown archetype", async () => {
    setMilestones(await loadParsedMap());
    expect(getArchetypeMilestones("no_such_archetype_xyz")).toEqual([]);
  });
});

describe("parseMilestoneRow — fail-loud validation", () => {
  const base = {
    id: "test_milestone",
    archetype_id: "warrior",
    tier: "power",
    level: 10,
    kind: "auto_grant",
    patron_deferred: false,
    specialization_options: [],
    grant: { name: "Test Grant", effect: "Does a thing.", flag: null },
    narration_cue: "A thing happens.",
  };

  test("accepts a valid row", () => {
    expect(() => parseMilestoneRow("test_milestone", base)).not.toThrow();
  });

  test("rejects a non-object row", () => {
    expect(() => parseMilestoneRow("x", null)).toThrow(/milestones\[x\]/);
    expect(() => parseMilestoneRow("x", [])).toThrow(/milestones\[x\]/);
  });

  test("rejects a tier outside the closed set", () => {
    expect(() => parseMilestoneRow("x", { ...base, tier: "ascension" })).toThrow(
      /milestones\[x\]\.tier/,
    );
  });

  test("rejects a kind outside the closed set", () => {
    expect(() => parseMilestoneRow("x", { ...base, kind: "passive_grant" })).toThrow(
      /milestones\[x\]\.kind/,
    );
  });

  test("rejects a non-integer level (parity with the Python int requirement)", () => {
    // Python parse_milestone_row requires int level (concern f499a5c2d1dd); a float like
    // 10.5 must fail on the TS side too, so the same shared row can't pass one loader and
    // fail the other (the cross-language parity discipline from f3f1560feb6b).
    expect(() => parseMilestoneRow("x", { ...base, level: 10.5 })).toThrow(
      /milestones\[x\]\.level/,
    );
  });

  test("rejects a non-boolean patron_deferred", () => {
    expect(() => parseMilestoneRow("x", { ...base, patron_deferred: "yes" })).toThrow(
      /milestones\[x\]\.patron_deferred/,
    );
  });

  test("rejects a malformed grant (missing effect)", () => {
    expect(() => parseMilestoneRow("x", { ...base, grant: { name: "X", flag: null } })).toThrow(
      /milestones\[x\]\.grant/,
    );
  });

  test("rejects a grant.flag that is neither string nor null", () => {
    // flag is the combat-math marker; a numeric flag must fail loud rather than silently
    // coerce, mirroring the abilities loader's scaling-not-string branch.
    expect(() =>
      parseMilestoneRow("x", { ...base, grant: { name: "X", effect: "Y", flag: 7 } }),
    ).toThrow(/milestones\[x\]\.grant\.flag/);
  });

  test("rejects a non-array specialization_options", () => {
    expect(() => parseMilestoneRow("x", { ...base, specialization_options: {} })).toThrow(
      /milestones\[x\]\.specialization_options/,
    );
  });

  test("rejects a malformed specialization option (missing description)", () => {
    const bad = {
      ...base,
      kind: "specialization_fork",
      level: 5,
      tier: "identity",
      grant: null,
      specialization_options: [{ id: "x_opt", name: "Opt" }],
    };
    expect(() => parseMilestoneRow("x", bad)).toThrow(/milestones\[x\]\.specialization_options/);
  });
});
