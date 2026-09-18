import { beforeEach, expect, mock, test } from "bun:test";
import type { SpellTier, TemplateItem } from "@divineruin/shared";
import { minLevelForSpellTier } from "@divineruin/shared";
import { dbMockFactory, makeRequest, resetMockDb, setQueryStubs } from "./activities-test-mock.ts";
import { setArchetypes } from "./archetypes.ts";
import {
  getAllTrainingPrograms,
  setTrainingPrograms,
  type TrainingProgramConfig,
} from "./activity_templates.ts";
import { listSpells, parseSpellRow, setSpells } from "./spells.ts";
import { archetypeRows, parseArchetypeCorpus } from "./test-fixtures/archetype-corpus.ts";
import { setupTrainingConfigFixture } from "./test-fixtures/training-config.ts";
// The launcher's payload builder itself, not a copy of its shape: this is the only place
// the HUD half and the start route meet in one process, so a rename on either side reds here.
import { getLaunchIntent } from "../../mobile/src/components/activity-launcher-strings.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleGetActivityTemplates } = await import("./activity-templates-api.ts");
const { handleCreateActivity } = await import("./activity_create.ts");

const SPELL_TIERS: SpellTier[] = ["cantrip", "minor", "standard", "major", "supreme"];
const spellRows = (await Bun.file(
  new URL("../../../content/spells.json", import.meta.url),
).json()) as Record<string, unknown>[];
function spellPrograms(): TrainingProgramConfig[] {
  return SPELL_TIERS.map((tier) => ({
    id: `${tier}_study`,
    name: `${tier} Study`,
    training_activity_type: `spell_${tier}`,
    stat: "intelligence",
    dc: 14,
    mentor_id: "scholar_emris",
  }));
}

beforeEach(() => {
  resetMockDb();
  setupTrainingConfigFixture();
  setSpells(
    new Map(spellRows.map((row) => [row.id as string, parseSpellRow(row.id as string, row)])),
  );
  setArchetypes(parseArchetypeCorpus());
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

test("training templates include spell programs with no choices for a classless player", async () => {
  const items = await getTrainingItems();
  expect(items.length).toBeGreaterThan(0);
  expect(items.map((item) => item.id)).toEqual(
    getAllTrainingPrograms().map((program) => program.id),
  );
  expect(items.map((item) => item.id)).toContain("combat_basics");
  expect(items.find((item) => item.id === "arcane_study")?.params.studiable_spell_ids).toEqual([]);
  expect(items.every((item) => item.active === null)).toBe(true);
});

test("a level-3 mage gets exactly unknown Arcane Standard spells", async () => {
  const known = "arcane_hold_person";
  setQueryStubs([
    { match: /data->>'class'.*data->>'level'/s, result: [{ class: "mage", level: "3" }] },
    { match: /FROM character_spells/, result: [{ spell_id: known }] },
  ]);
  const item = (await getTrainingItems()).find((candidate) => candidate.id === "arcane_study")!;
  const expected = listSpells()
    .filter(
      (spell) => spell.source === "arcane" && spell.spell_tier === "standard" && spell.id !== known,
    )
    .map((spell) => spell.id)
    .sort();
  expect(item.params.studiable_spell_ids).toEqual(expected);
});

test("level and source gates keep the row but empty its choices", async () => {
  for (const player of [
    { class: "mage", level: "2" },
    { class: "warrior", level: "20" },
  ]) {
    resetMockDb();
    setQueryStubs([{ match: /FROM players/, result: [player] }]);
    const item = (await getTrainingItems()).find((candidate) => candidate.id === "arcane_study")!;
    expect(item.params.studiable_spell_ids).toEqual([]);
  }
});

test("the launcher's own payload starts the activity", async () => {
  setQueryStubs([
    { match: /FROM players/, result: [{ class: "mage", level: "3" }] },
    { match: /FROM character_spells/, result: [] },
  ]);
  const item = (await getTrainingItems()).find((candidate) => candidate.id === "arcane_study")!;
  const choice = getLaunchIntent("training", item);
  expect(choice).toMatchObject({ kind: "choose-spell" });
  const spellId = (choice as { spellIds: string[] }).spellIds[0]!;
  const ready = getLaunchIntent("training", item, spellId);
  expect(ready).toMatchObject({ kind: "ready" });
  setQueryStubs([
    { match: /FROM players/, result: [{ class: "mage", level: "3" }] },
    { match: /FROM character_spells/, result: [] },
    { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] },
  ]);
  const response = await handleCreateActivity(
    makeRequest("POST", "/api/activities", {
      type: "training",
      parameters: (ready as { params: Record<string, unknown> }).params,
    }),
    "player_1",
  );
  expect(response.status).toBe(200);
});

test("a martial's spell row is disabled with a reason, so the launcher never posts", async () => {
  setQueryStubs([{ match: /FROM players/, result: [{ class: "warrior", level: "20" }] }]);
  const item = (await getTrainingItems()).find((candidate) => candidate.id === "arcane_study")!;
  const intent = getLaunchIntent("training", item);
  expect(intent.kind).toBe("disabled");
  expect((intent as { reason: string }).reason.length).toBeGreaterThan(0);
});

test("template ids equal the real start route acceptance set for every archetype and tier", async () => {
  const archetypes = parseArchetypeCorpus();
  const programs = spellPrograms();
  setTrainingPrograms(new Map(programs.map((program) => [program.id, program])));
  const checked = new Set<string>();
  const mismatches: string[] = [];
  // Constraint 12's floor: the spell catalog is a corpus this walk reads, so an emptied
  // content/spells.json (or one tier/source bucket of it) would agree at [] on both sides
  // and pass vacuously. Every caster row that reaches its floor must have produced choices.
  const offeredChoices = new Set<string>();
  const expectStudiable = new Set<string>();

  for (const archetype of archetypes.values()) {
    for (const tier of SPELL_TIERS) {
      const floor = archetype.magic_source === null ? null : minLevelForSpellTier(archetype, tier);
      const levels = floor === null ? [1, 20] : [...new Set([Math.max(1, floor - 1), floor])];
      const eligible = listSpells().find(
        (spell) =>
          spell.spell_tier === tier &&
          (archetype.magic_source === "cross" || spell.source === archetype.magic_source),
      );
      const known = eligible?.id;

      for (const level of levels) {
        const player = { class: archetype.id, level: String(level) };
        resetMockDb();
        setQueryStubs([
          { match: /FROM players/, result: [player] },
          { match: /FROM character_spells/, result: known ? [{ spell_id: known }] : [] },
        ]);
        const item = (await getTrainingItems()).find(
          (candidate) => candidate.id === `${tier}_study`,
        )!;
        const accepted: string[] = [];
        for (const spell of listSpells()) {
          resetMockDb();
          setQueryStubs([
            { match: /FROM players/, result: [player] },
            {
              match: /FROM character_spells/,
              result: spell.id === known ? [{ spell_id: known }] : [],
            },
            { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] },
          ]);
          const response = await handleCreateActivity(
            makeRequest("POST", "/api/activities", {
              type: "training",
              parameters: { program_id: `${tier}_study`, spell_id: spell.id },
            }),
            "player_1",
          );
          if (response.status === 200) accepted.push(spell.id);
        }
        const listed = (item.params.studiable_spell_ids as string[]).slice().sort();
        accepted.sort();
        if (listed.length > 0) offeredChoices.add(`${archetype.id}:${tier}`);
        if (floor !== null && level === floor) expectStudiable.add(`${archetype.id}:${tier}`);
        if (JSON.stringify(listed) !== JSON.stringify(accepted)) {
          mismatches.push(`${archetype.id}:${tier}:level-${level}`);
        }
        if (known) {
          expect(item.params.studiable_spell_ids as string[]).not.toContain(known);
          expect(accepted).not.toContain(known);
        }
      }
      checked.add(`${archetype.id}:${tier}`);
    }
  }

  expect(archetypeRows.length).toBeGreaterThan(0);
  expect(listSpells().length).toBeGreaterThan(0);
  expect(mismatches).toEqual([]);
  expect(expectStudiable.size).toBeGreaterThan(0);
  expect(offeredChoices).toEqual(expectStudiable);
  expect(archetypes.size).toBe(archetypeRows.length);
  expect(checked.size).toBe(archetypeRows.length * SPELL_TIERS.length);
  expect(checked).toEqual(
    new Set([...archetypes.keys()].flatMap((id) => SPELL_TIERS.map((tier) => `${id}:${tier}`))),
  );
});
