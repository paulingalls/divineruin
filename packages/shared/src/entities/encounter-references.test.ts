import ts from "typescript";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test, expect } from "bun:test";
import { validateEncounterReferences } from "./encounter";

const corpus = (await Bun.file(
  new URL("../../fixtures/encounter_references.json", import.meta.url),
).json()) as {
  invalid: { name: string; field: string; encounter: unknown }[];
  valid: { recommended_party_level: number }[];
};
const catalog = (await Bun.file(
  new URL("../../../../content/creatures.json", import.meta.url),
).json()) as { id: string }[];
const ids = new Set<string>(catalog.map((row: { id: string }) => row.id));
test("shared guard corpus retains its invalid and level-boundary cases", () => {
  expect(corpus.invalid.length).toBeGreaterThanOrEqual(50);
  expect(corpus.valid.length).toBeGreaterThanOrEqual(2);
});
for (const row of corpus.invalid) {
  test(`shared reference cases ${row.name}`, () => {
    expect(() => validateEncounterReferences(row.encounter, ids)).toThrow(row.field);
  });
}
for (const row of corpus.valid) {
  test(`recommended party level cases ${row.recommended_party_level}`, () => {
    expect(() => validateEncounterReferences(row, ids)).not.toThrow();
  });
}
test("all ten templates", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/encounter_templates.json", import.meta.url),
  ).json()) as unknown[];
  expect(rows).toHaveLength(10);
  expect(ids.size).toBeGreaterThan(0);
  for (const row of rows) validateEncounterReferences(row, ids);
});

test("EncounterEnemy compiler rejects flat entries and missing required fields", () => {
  const directory = mkdtempSync(join(tmpdir(), "encounter-types-"));
  const path = join(directory, "contract.ts");
  try {
    const module = new URL("./encounter", import.meta.url).pathname;
    const entries = [
      '{id: "one", creature_id: "bandit", role: "standard"}',
      '{id: "one", creature_id: "bandit"}',
      '{id: "one", role: "standard"}',
      '{creature_id: "bandit", role: "standard"}',
      ...[
        "hp",
        "ac",
        "level",
        "tier",
        "name",
        "attributes",
        "action_pool",
        "xp_value",
        "loot_table_id",
        "category",
        "sound_signature",
        "signature_ability",
        "legendary_actions",
        "currency",
        "audio",
        "narration",
        "override",
      ].map((field) => `{id: "one", creature_id: "bandit", role: "standard", ${field}: 1}`),
    ];
    writeFileSync(
      path,
      `import type { EncounterEnemy, Encounter } from ${JSON.stringify(module)};\n` +
        entries
          .map((entry, index) => `const entry${index}: EncounterEnemy = ${entry};`)
          .join("\n") +
        "\nconst origin = {x:0, y:0, z:0};" +
        "\nconst scene_placement = {party_start:origin, companion_start:origin, actors:{one:origin}, locations:{}, zones:{}};" +
        '\nconst correct: Encounter = {id:"e", name:"e", difficulty:"easy", enemies:[entry0], recommended_party_level:1, scene_placement};' +
        '\nconst missingLevel: Encounter = {id:"e", name:"e", difficulty:"easy", enemies:[entry0], scene_placement};',
    );
    const program = ts.createProgram([path], {
      noEmit: true,
      strict: true,
      skipLibCheck: true,
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
    });
    const errors = ts
      .getPreEmitDiagnostics(program)
      .filter((error) => error.file?.fileName === path);
    expect(errors).toHaveLength(entries.length);
    expect(errors.every((error) => error.code === 2741 || error.code === 2353)).toBe(true);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
