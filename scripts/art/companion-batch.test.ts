import { expect, mock, test } from "bun:test";
import type { CompanionArtRow } from "./companion-batch.ts";

const paidSeam = mock(() => {
  throw new Error("paid image seam called while building companion batch");
});

await mock.module("../../apps/server/src/image-gen.ts", () => ({
  generateImage: paidSeam,
  computeAssetId: paidSeam,
  getAssetPath: paidSeam,
}));

test("the MVP batch derives exactly two portrait rows per companion without image generation", async () => {
  const companions = (await Bun.file(
    new URL("../../content/companions.json", import.meta.url),
  ).json()) as CompanionArtRow[];
  const { buildCompanionBatch } = await import("./companion-batch.ts");
  const { MVP_BATCH } = await import("./mvp-batch.ts");

  const expected = buildCompanionBatch(companions);
  expect(expected).toHaveLength(8);
  expect(expected.map((row) => row.assetId)).toEqual(
    companions.flatMap((companion: { portrait: { primary: string; alert: string } }) => [
      companion.portrait.primary,
      companion.portrait.alert,
    ]),
  );
  for (let index = 0; index < companions.length; index++) {
    const companion = companions[index] as {
      name: string;
      appearance: string;
      species: string;
      gender: string;
      age: string;
    };
    const vars = {
      appearance: companion.appearance,
      species: companion.species,
      gender: companion.gender,
      age: companion.age,
    };
    expect(expected[index * 2]).toMatchObject({
      templateId: "companion_portrait_primary",
      vars,
      label: `${companion.name} primary`,
    });
    expect(expected[index * 2 + 1]).toMatchObject({
      templateId: "companion_portrait_alert",
      vars,
      label: `${companion.name} alert`,
    });
  }

  expect(
    MVP_BATCH.filter((row) => row.templateId.startsWith("companion_portrait_")),
  ).toEqual(expected);
  expect(paidSeam).not.toHaveBeenCalled();
});
