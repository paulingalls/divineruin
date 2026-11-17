import { expect, test } from "bun:test";
import type { QuestCompletionCondition, QuestStageComplete } from "./quest";

const conditionFields = {
  location_reached: ["location"],
  knowledge_acquired: ["required_info", "sources"],
  combat_completed: ["encounter", "outcome"],
  item_discovered: ["items", "location"],
  npc_interaction: ["npc", "topic"],
  decision_made: ["decision", "options"],
} satisfies {
  [K in QuestCompletionCondition["type"]]: readonly (keyof Extract<
    QuestCompletionCondition,
    { type: K }
  >)[];
};
const rewardFields = { xp: "number", world_effects: "array" } as const satisfies {
  [K in keyof Pick<QuestStageComplete, "xp" | "world_effects">]: string;
};

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected an object");
  return value as Record<string, unknown>;
}
function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error("Expected an array");
  return value;
}
const records = (value: unknown) => array(value).map(object);
async function content(name: string) {
  const parsed: unknown = await Bun.file(
    new URL(`../../../../content/${name}.json`, import.meta.url),
  ).json();
  return records(parsed);
}

test("authored quest conditions and rewards satisfy the shared contract", async () => {
  const quests = await content("quests");
  expect(quests.length).toBeGreaterThan(0);
  for (const quest of quests) {
    const stages = records(quest.stages);
    expect(stages.length).toBeGreaterThan(0);
    for (const stage of stages) {
      expect(Object.hasOwn(stage, "branches")).toBe(false);
      const cc = object(stage.completion_conditions);
      expect(typeof cc.type).toBe("string");
      expect(Object.hasOwn(conditionFields, String(cc.type))).toBe(true);
      const fields = conditionFields[cc.type as keyof typeof conditionFields];
      expect(Object.keys(cc).sort()).toEqual(["type", ...fields].sort());
      if (cc.type === "decision_made") {
        const options = object(cc.options);
        expect(Object.keys(options).length).toBeGreaterThan(0);
        for (const [id, option] of Object.entries(options)) {
          expect(id.length).toBeGreaterThan(0);
          const details = object(option);
          expect(typeof details.description).toBe("string");
          expect(String(details.description).length).toBeGreaterThan(0);
          expect(array(details.effects).length).toBeGreaterThan(0);
          for (const effect of array(details.effects)) expect(typeof effect).toBe("string");
        }
      }
      if (stage.on_complete) {
        const reward = object(stage.on_complete);
        for (const [key, kind] of Object.entries(rewardFields)) {
          if (kind === "array") expect(Array.isArray(reward[key])).toBe(true);
          else expect(typeof reward[key]).toBe(kind);
        }
      }
    }
  }
});

test("Greyvale eight-stage arc resolves its decisions, scenes and fights", async () => {
  const quests = await content("quests");
  const quest = quests.find((q) => q.id === "greyvale_anomaly");
  if (!quest) throw new Error("Greyvale quest missing");
  const stages = records(quest.stages);
  expect(stages.map((s) => s.id)).toEqual([
    "stage_1_investigate",
    "stage_2_gather_intel",
    "stage_3_first_contact",
    "stage_4_the_ruins",
    "stage_ruins_fight",
    "stage_inner_chamber_artifact",
    "stage_artifact_choice",
    "stage_5_return",
  ]);
  const encounters = await content("encounter_templates");
  const scenes = await content("scenes");
  const indices: unknown[] = [];
  for (const entry of records(quest.scene_graph)) {
    expect(scenes.some((s) => s.id === entry.scene_id)).toBe(true);
    indices.push(...array(entry.stage_refs));
  }
  const graph = records(quest.scene_graph);
  expect(graph.find((e) => e.scene_id === "scene_ruins_exploration")?.stage_refs).toEqual([
    3, 4, 5, 6,
  ]);
  expect(graph.find((e) => e.scene_id === "scene_return_to_accord")?.stage_refs).toEqual([7]);
  expect(indices.sort()).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  for (const stage of stages) {
    const cc = object(stage.completion_conditions);
    if (cc.type === "combat_completed")
      expect(encounters.some((e) => e.id === cc.encounter)).toBe(true);
    expect(cc.encounter).not.toBe("ruins_guardian");
  }
  expect(stages[4]!.completion_conditions).toEqual({
    type: "combat_completed",
    encounter: "ruins_mawling_pair",
    outcome: "victory",
  });
  const reward = object(stages[4]!.on_complete);
  expect(reward.xp).toBe(100);
  expect(reward.rewards ?? []).toEqual([]);
  expect(reward.world_effects).toEqual([]);
  const xp = (end: number) =>
    stages.slice(0, end).reduce((sum, s) => {
      const amount = object(s.on_complete).xp;
      if (typeof amount !== "number") throw new Error("Expected XP number");
      return sum + amount;
    }, 0);
  expect(stages[5]!.completion_conditions).toEqual({
    type: "location_reached",
    location: "greyvale_ruins_inner",
  });
  expect(stages[5]!.target_location_id).toBe("greyvale_ruins_inner");
  expect(object(stages[5]!.on_complete)).toEqual({
    xp: 0,
    world_effects: [],
    rewards: [{ item: "veythar_sealed_artifact", quantity: 1 }],
    narrative_beat: expect.any(String),
  });
  expect([xp(4), xp(5), xp(6), xp(7), xp(8)]).toEqual([475, 575, 575, 575, 775]);
  for (const [id, decision, expected] of [
    ["greyvale_anomaly", "artifact_choice", ["keep_artifact", "show_companion"]],
    [
      "defend_millhaven",
      "fortification_choice",
      ["north_barricade", "watchtower", "evacuation_supplies"],
    ],
  ] as const) {
    const stages = records(quests.find((q) => q.id === id)!.stages);
    const cc = stages
      .map((s) => object(s.completion_conditions))
      .find((c) => c.decision === decision);
    expect(cc).toBeDefined();
    expect(Object.keys(object(cc!.options)).sort()).toEqual([...expected].sort());
  }
});
