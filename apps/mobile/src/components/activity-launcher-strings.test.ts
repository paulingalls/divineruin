import { test, expect } from "bun:test";
import {
  activeText,
  errandBusyLabel,
  errandDestinationPrompt,
  formatTimeRemaining,
  getActivityGroupState,
  getLaunchIntent,
  isStartVisible,
  mode,
  trainingBusyLabel,
} from "@/components/activity-launcher-strings";
import type { ActiveStatus, TemplateGroup, TemplateItem } from "@divineruin/shared";

test("errand strings name the assigned companion", () => {
  expect(errandBusyLabel("Sable", "Scouting Run")).toBe("Sable is on a Scouting Run");
  expect(errandDestinationPrompt("Sable")).toBe("Where should Sable go?");
});

test("every companion gets their own name, not Kael's", () => {
  for (const name of ["Kael", "Lira", "Tam", "Sable"]) {
    expect(errandBusyLabel(name, "Errand")).toBe(`${name} is on a Errand`);
    expect(errandDestinationPrompt(name)).toBe(`Where should ${name} go?`);
  }
});

test("a missing companion name degrades to a neutral noun, never to Kael", () => {
  expect(errandDestinationPrompt(null)).toBe("Where should your companion go?");
  expect(errandBusyLabel(null, "Scouting Run")).toBe("Your companion is on a Scouting Run");
});

test("time remaining reads as a spoken countdown, and completes at zero", () => {
  // +30s of slack on each deadline: formatTimeRemaining reads Date.now() itself, so an
  // exact 2h15m deadline floors to "2h 14m" the moment the clock ticks between the two
  // reads — a ~7%-per-run flake in the merge gate, not a formatter bug.
  const inHours = new Date(Date.now() + 2 * 3_600_000 + 15 * 60_000 + 30_000).toISOString();
  const past = new Date(Date.now() - 1000).toISOString();
  expect(formatTimeRemaining(inHours)).toBe("2h 15m remaining");
  expect(formatTimeRemaining(new Date(Date.now() + 90_000).toISOString())).toBe("1m remaining");
  expect(formatTimeRemaining(past)).toBe("completing...");
});

test("active text and mode distinguish waiting from running", () => {
  const past = new Date(Date.now() - 1000).toISOString();
  const waiting: ActiveStatus = {
    startTime: "2026-09-17T10:00:00.000Z",
    resolveAtEstimate: past,
    percentEstimate: 100,
    isAwaitingDecision: true,
  };
  const runningFuture: ActiveStatus = {
    ...waiting,
    resolveAtEstimate: new Date(Date.now() + 90_000).toISOString(),
    percentEstimate: 50,
    isAwaitingDecision: false,
  };
  const runningPast: ActiveStatus = { ...waiting, isAwaitingDecision: false };

  expect(activeText(waiting)).toBe("waiting on you");
  expect(activeText(waiting)).not.toContain("remaining");
  expect(activeText(waiting)).not.toContain("completing");
  expect(mode(waiting)).toBe("WAITING");
  expect(activeText(runningFuture)).toBe("1m remaining");
  expect(activeText(runningPast)).toBe("completing...");
  expect(mode(runningPast)).toBe("IN PROGRESS");
});

const inactive = {
  duration: "2-4h",
  materials: null,
  active: null,
};
const runningTrainingGroup: TemplateGroup = {
  type: "training",
  label: "Training",
  items: [
    {
      ...inactive,
      id: "combat_basics",
      name: "Combat Fundamentals",
      params: { program_id: "combat_basics" },
    },
    {
      ...inactive,
      id: "focused_practice",
      name: "Focused Practice",
      params: { program_id: "focused_practice" },
    },
    {
      id: "arcane_study",
      name: "Arcane Study",
      duration: "2-4h",
      params: { program_id: "arcane_study" },
      materials: null,
      active: {
        startTime: "2026-09-17T14:00:00.000Z",
        resolveAtEstimate: "2026-09-17T16:00:00.000Z",
        percentEstimate: 50,
        isAwaitingDecision: false,
      },
    },
  ],
};

test("a running training program locks the group and names the cycle", () => {
  const state = getActivityGroupState(runningTrainingGroup);

  expect(state.isGroupLocked).toBe(true);
  expect(state.groupBusy).toBe(true);
  expect(state.activeItem?.name).toBe("Arcane Study");
  expect(trainingBusyLabel(state.activeItem!.name)).toBe("Currently training: Arcane Study");
});

test("a running training program hides every start action", () => {
  const state = getActivityGroupState(runningTrainingGroup);

  expect(runningTrainingGroup.items.every((item) => !isStartVisible(item, state))).toBe(true);
});

const trainingItem = (params: Record<string, unknown>): TemplateItem => ({
  ...inactive,
  id: "arcane_study",
  name: "Arcane Study",
  params: { program_id: "arcane_study", ...params },
});

test("launch policy preserves ordinary training and crafting payloads", () => {
  expect(getLaunchIntent("training", trainingItem({}))).toEqual({
    kind: "ready",
    params: { program_id: "arcane_study" },
  });
  expect(
    getLaunchIntent("crafting", {
      ...trainingItem({ recipe_id: "iron_sword" }),
      id: "iron_sword",
    }),
  ).toEqual({ kind: "ready", params: { recipe_id: "iron_sword" } });
});

test("spell training chooses before posting and preserves the canonical id", () => {
  const item = trainingItem({ studiiable_typo: [], studiable_spell_ids: ["arcane_hold_person"] });
  expect(getLaunchIntent("training", item)).toEqual({
    kind: "choose-spell",
    spellIds: ["arcane_hold_person"],
  });
  expect(getLaunchIntent("training", item, "arcane_hold_person")).toEqual({
    kind: "ready",
    params: { program_id: "arcane_study", spell_id: "arcane_hold_person" },
  });
  expect(() => getLaunchIntent("training", item, "Hold Person")).toThrow(/not available/);
});

test("empty spell choices disable launch with a stable reason", () => {
  expect(getLaunchIntent("training", trainingItem({ studiable_spell_ids: [] }))).toEqual({
    kind: "disabled",
    reason: "No spells available to study.",
  });
});

test("each malformed spell choice row is disabled without blocking its sibling", () => {
  for (const malformedSpellIds of ["arcane_hold_person", ["arcane_hold_person", 42], [""]]) {
    const items = [
      trainingItem({ studiable_spell_ids: malformedSpellIds }),
      {
        ...trainingItem({}),
        id: "combat_basics",
        name: "Combat Fundamentals",
        params: { program_id: "combat_basics" },
      },
    ];

    const intents = items.map((item) => getLaunchIntent("training", item));

    expect(intents).toHaveLength(2);
    expect(intents[0]).toEqual({
      kind: "disabled",
      reason: "Spell choices are unavailable.",
    });
    expect(intents[1]).toEqual({
      kind: "ready",
      params: { program_id: "combat_basics" },
    });
  }
});
