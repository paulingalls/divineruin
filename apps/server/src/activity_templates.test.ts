import { beforeEach, describe, expect, mock, test } from "bun:test";
import { dbMockFactory, resetMockDb, setQueryStubs } from "./activities-test-mock.ts";
import { setupErrandTemplatesFixture } from "./test-fixtures/errand-templates.ts";
import { setupTrainingConfigFixture } from "./test-fixtures/training-config.ts";
import type { TemplateItem } from "@divineruin/shared";
import type { TrainingProgramConfig } from "./activity_templates.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleGetActivityTemplates } = await import("./activity-templates-api.ts");
const { handleGetCatchUpFeed } = await import("./catchup.ts");
const { getErrandTemplate, parseProgramRows, setTrainingPrograms } =
  await import("./activity_templates.ts");
const { parseActivityTypeRows } = await import("./training_state_machine.ts");

beforeEach(() => {
  resetMockDb();
  setupErrandTemplatesFixture();
  setupTrainingConfigFixture();
});

async function getTrainingItems(): Promise<TemplateItem[]> {
  const response = await handleGetActivityTemplates("player_1");
  const payload = (await response.json()) as {
    groups: { type: string; items: TemplateItem[] }[];
  };
  const training = payload.groups.find((group) => group.type === "training");

  expect(training).toBeDefined();
  return training!.items;
}

describe("training program catalog", () => {
  const programRows = async () =>
    (
      (await Bun.file(
        new URL("../../../content/training_programs.json", import.meta.url),
      ).json()) as Record<string, unknown>[]
    ).map(({ id, ...data }) => ({ id: id as string, data }));

  const activityTypeRows = async () =>
    (
      (await Bun.file(
        new URL("../../../content/training_activity_types.json", import.meta.url),
      ).json()) as Record<string, unknown>[]
    ).map(({ id, ...data }) => ({ id: id as string, data }));

  test("the real authored catalogs are non-empty and every program names an activity type", async () => {
    const programs = await programRows();
    const types = await activityTypeRows();
    expect(programs.length).toBeGreaterThan(0);
    expect(types.length).toBeGreaterThan(0);

    const activityTypes = parseActivityTypeRows(types);
    expect(parseProgramRows(programs, activityTypes).size).toBe(programs.length);
  });

  test("rejects a bogus non-spell activity type where the program is authored", async () => {
    const programs = await programRows();
    const activityTypes = parseActivityTypeRows(await activityTypeRows());
    const [program] = programs;
    expect(program).toBeDefined();
    const bad = {
      id: program!.id,
      data: { ...(program!.data as object), training_activity_type: "recipe_unpublished" },
    };
    expect(() => parseProgramRows([bad], activityTypes)).toThrow(
      /training_activity_type.*recipe_unpublished/,
    );
  });

  test("an empty activity type catalog fails loud", async () => {
    const programs = await programRows();
    expect(() => parseProgramRows(programs, new Map())).toThrow(
      /training_activity_types produced no rows/,
    );
  });

  test("an empty authored catalog fails loud", () => {
    expect(() => parseProgramRows([], new Map([["technique_base", {} as never]]))).toThrow(
      /training_programs produced no rows/,
    );
  });

  test("a duplicate row id fails loud", async () => {
    const [first] = await programRows();
    const activityTypes = parseActivityTypeRows(await activityTypeRows());
    expect(() => parseProgramRows([first!, first!], activityTypes)).toThrow(/duplicate/);
  });
});

test("a render failure is a 500, never a successful empty HUD", async () => {
  setTrainingPrograms(
    new Map([
      [
        "broken_program",
        {
          id: "broken_program",
          name: "Broken Program",
          training_activity_type: "recipe_unpublished",
          stat: "intelligence",
          dc: 10,
          mentor_id: "mentor_missing",
        } as unknown as TrainingProgramConfig,
      ],
    ]),
  );

  const response = await handleGetActivityTemplates("player_1");
  const payload = (await response.json()) as Record<string, unknown>;

  expect(response.status).toBe(500);
  expect(payload).toEqual({ error: "Internal server error" });
  expect(payload).not.toHaveProperty("groups");
});

test("a running technique cycle is active on its training program", async () => {
  const startTime = "2026-09-17T10:00:00.000Z";
  const resolveAt = "2026-09-17T12:00:00.000Z";
  setQueryStubs([
    {
      match: /FROM training_activities[\s\S]*state != 'complete'/,
      result: [
        {
          data: { program_id: "combat_basics" },
          state: "running_first_half",
          created_at: startTime,
          transition_at: resolveAt,
        },
      ],
    },
  ]);

  const items = await getTrainingItems();
  const activeItem = items.find((item) => item.active !== null);

  expect(activeItem).toMatchObject({
    id: "combat_basics",
    name: "Combat Fundamentals",
    active: { startTime, resolveAtEstimate: resolveAt, isAwaitingDecision: false },
  });
  expect(
    items.filter((item) => item.id !== "combat_basics").every((item) => item.active === null),
  ).toBe(true);
});

test("a running spell cycle is included as an active-only training program", async () => {
  const startTime = "2026-09-17T14:00:00.000Z";
  const resolveAt = "2026-09-17T16:00:00.000Z";
  setQueryStubs([
    {
      match: /FROM training_activities[\s\S]*state != 'complete'/,
      result: [
        {
          data: JSON.stringify({ program_id: "arcane_study" }),
          state: "running_second_half",
          created_at: startTime,
          transition_at: resolveAt,
        },
      ],
    },
  ]);

  const items = await getTrainingItems();
  const activeItem = items.find((item) => item.active !== null);

  expect(activeItem).toMatchObject({
    id: "arcane_study",
    name: "Arcane Study",
    active: { startTime, resolveAtEstimate: resolveAt, isAwaitingDecision: false },
  });
  expect(
    items.filter((item) => item.id !== "arcane_study").every((item) => item.active === null),
  ).toBe(true);
});

// learn(kind="variant") writes variant_id and no program_id, and no training program carries
// technique_mentor_variant — so this row has no program row of its own to sit on, and it holds
// the training slot all the same.
test("a running mentor-variant cycle is active on a row of its own", async () => {
  const startTime = "2026-09-17T09:00:00.000Z";
  const resolveAt = "2026-09-17T14:00:00.000Z";
  setQueryStubs([
    {
      match: /FROM training_activities[\s\S]*state != 'complete'/,
      result: [
        {
          data: {
            variant_id: "warrior_cleaving_blow_drathian",
            ability_id: "warrior_cleaving_blow",
            first_half_seconds: 18000,
          },
          activity_type: "technique_mentor_variant",
          state: "running_first_half",
          created_at: startTime,
          transition_at: resolveAt,
        },
      ],
    },
  ]);

  const items = await getTrainingItems();
  const activeItems = items.filter((item) => item.active !== null);

  expect(activeItems).toMatchObject([
    {
      id: "warrior_cleaving_blow_drathian",
      name: "Warrior Cleaving Blow Drathian",
      active: { startTime, resolveAtEstimate: resolveAt, isAwaitingDecision: false },
    },
  ]);
});

test("an awaiting cycle agrees with catchup and keeps its past transition time", async () => {
  const startTime = "2026-09-17T10:00:00.000Z";
  const pastTransition = "2026-09-17T12:00:00.000Z";
  const row = {
    id: "training_waiting_1",
    activity_type: "technique_base",
    state: "awaiting_decision",
    data: { program_id: "combat_basics", program_name: "Combat Fundamentals" },
    created_at: startTime,
    updated_at: pastTransition,
    transition_at: pastTransition,
  };
  // Both handlers read training_activities in one test, so each stub names its own
  // SELECT list: catchup's predicate also contains `state != 'complete'`, and the mock
  // hands the first unconsumed match its rows.
  setQueryStubs([
    {
      match:
        /SELECT data, activity_type, state, created_at, transition_at[\s\S]*FROM training_activities/,
      result: [row],
    },
    {
      match: /SELECT id, activity_type, state, data, transition_at[\s\S]*FROM training_activities/,
      result: [row],
    },
  ]);

  const items = await getTrainingItems();
  const response = await handleGetCatchUpFeed(new Request("http://localhost"), "player_1");
  const payload = (await response.json()) as { items: { id: string; type: string }[] };
  const active = items.find((item) => item.id === "combat_basics")!.active;
  const feedItem = payload.items.find((item) => item.id === row.id);

  expect(active).toMatchObject({
    startTime,
    resolveAtEstimate: pastTransition,
    isAwaitingDecision: true,
  });
  expect(feedItem?.type).toBe("pending_decision");
  expect(active!.isAwaitingDecision).toBe(feedItem?.type === "pending_decision");
  expect(active!.isAwaitingDecision).toBe(true);
});

test("an awaiting mentor-variant cycle preserves waiting state on its own row", async () => {
  const startTime = "2026-09-17T09:00:00.000Z";
  const pastTransition = "2026-09-17T14:00:00.000Z";
  setQueryStubs([
    {
      match: /FROM training_activities[\s\S]*state != 'complete'/,
      result: [
        {
          data: { variant_id: "warrior_cleaving_blow_drathian" },
          activity_type: "technique_mentor_variant",
          state: "awaiting_decision",
          created_at: startTime,
          transition_at: pastTransition,
        },
      ],
    },
  ]);

  const items = await getTrainingItems();

  expect(items.find((item) => item.id === "warrior_cleaving_blow_drathian")?.active).toMatchObject({
    startTime,
    resolveAtEstimate: pastTransition,
    isAwaitingDecision: true,
  });
});

// Durations must match the spec's Errand Types table
// (docs/game_mechanics/game_mechanics_core.md L824-829), expressed in seconds.
// Templates are now DB-loaded from content/errand_templates.json; the fixture
// loads that same JSON, so this pins the shared source against the spec.
describe("errand template durations match spec", () => {
  const HOUR = 3600;
  const expected: Record<string, { min: number; max: number }> = {
    scout: { min: 4 * HOUR, max: 8 * HOUR }, // 4-8 hrs
    social: { min: 3 * HOUR, max: 6 * HOUR }, // 3-6 hrs
    acquire: { min: 4 * HOUR, max: 10 * HOUR }, // 4-10 hrs
    relationship: { min: 2 * HOUR, max: 4 * HOUR }, // 2-4 hrs
  };

  for (const [type, { min, max }] of Object.entries(expected)) {
    test(`${type} duration is ${min / HOUR}-${max / HOUR}h`, () => {
      const template = getErrandTemplate(type);
      expect(template).toBeDefined();
      expect(template!.duration_min_seconds).toBe(min);
      expect(template!.duration_max_seconds).toBe(max);
    });
  }
});
