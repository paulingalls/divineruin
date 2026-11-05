import { expect, test } from "bun:test";
import { validateCreatureJson } from "./creature";

const catalog = (await Bun.file(
  new URL("../../../../content/creatures.json", import.meta.url),
).json()) as Record<string, unknown>[];

for (const [value, diagnostic] of [
  [undefined, "terrains: required"],
  ["forest", "terrains: expected array"],
  [[], "terrains: expected non-empty array"],
  [["forest", "atlantis"], "terrains[1]: unknown terrain"],
  [[{}], "terrains[0]: expected string"],
] as const) {
  test(diagnostic, () => {
    const candidate = { ...catalog[0], terrains: value };
    expect(validateCreatureJson(JSON.stringify([candidate]))).toEqual([diagnostic]);
  });
}
