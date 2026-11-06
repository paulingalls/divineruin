import { expect, test } from "bun:test";
import corpus from "../../fixtures/god_profiles.json";
import catalog from "../../../../content/gods.json";
import { validateGods } from "./index";

type Profile = (typeof corpus.valid)[number]["profile"];
function withProfile(profile: unknown): unknown[] {
  return [structuredClone(profile), ...structuredClone(catalog.slice(1))];
}

const generated = Object.entries(corpus.vocabulary).flatMap(([kind, spec]) =>
  spec.predicates.map((applies_to) => {
    const profile = structuredClone(corpus.valid[0]!.profile);
    const modified: unknown = {
      ...profile,
      layer_2_resonance: {
        ...profile.layer_2_resonance,
        modifiers: [{ kind, applies_to, value: spec.sample }],
      },
    };
    return { id: `${kind}/${applies_to}`, profile: modified };
  }),
);

test("the actual catalog validates against the exact ten-patron floor", () => {
  expect(corpus.patron_ids).toHaveLength(10);
  expect(new Set(corpus.patron_ids).size).toBe(10);
  expect(catalog).toHaveLength(10);
  expect(catalog.map((g) => g.god_id).sort()).toEqual([...corpus.patron_ids].sort());
  expect(Object.is(validateGods(catalog), catalog)).toBe(true);
  expect(corpus.valid.length).toBeGreaterThan(0);
  expect(corpus.invalid.length).toBeGreaterThan(0);
  expect(generated.length).toBeGreaterThan(0);
});

for (const entry of [...corpus.valid, ...generated]) {
  test(`valid profile: ${entry.id}`, () => {
    const rows = withProfile(entry.profile);
    expect(Object.is(validateGods(rows), rows)).toBe(true);
    expect(rows[0]).toEqual(entry.profile);
  });
}
for (const entry of corpus.invalid) {
  test(`invalid profile: ${entry.id}`, () => {
    expect(() => validateGods(withProfile(entry.profile))).toThrow(
      `${entry.patron}.${entry.field}`,
    );
  });
}

for (const shape of [null, {}, [], [null]]) {
  test(`invalid catalog: ${JSON.stringify(shape)}`, () => {
    expect(() => validateGods(shape)).toThrow(/gods|god_id/);
  });
}

for (const defect of [
  "duplicate_patron",
  "duplicate_ability",
  "cross_catalog_ability",
  "missing_id",
  "blank_id",
  "numeric_id",
]) {
  test(`invalid catalog identity: ${defect}`, () => {
    const rows: unknown[] = structuredClone(catalog);
    const profile = structuredClone(corpus.valid[0]!.profile);
    let field: string;
    if (defect === "duplicate_patron") {
      rows.push(structuredClone(catalog[0]));
      field = "veythar.god_id";
    } else if (defect === "duplicate_ability") {
      profile.layer_3_tier_abilities.devoted.id = profile.layer_3_tier_abilities.acknowledged.id;
      rows[0] = profile;
      field = "veythar.layer_3_tier_abilities.devoted.id";
    } else if (defect === "cross_catalog_ability") {
      rows[0] = profile;
      rows[1] = { ...structuredClone(profile), god_id: "veythar_fixture" };
      field = "veythar_fixture.layer_3_tier_abilities.acknowledged.id";
    } else {
      const changed: Record<string, unknown> = { ...profile };
      if (defect === "missing_id") delete changed.god_id;
      else changed.god_id = defect === "blank_id" ? " " : 2;
      rows[0] = changed;
      field = "gods[0].god_id";
    }
    expect(() => validateGods(rows)).toThrow(field);
  });
}

for (const value of [Infinity, -Infinity, NaN]) {
  test(`nonfinite runtime value: ${value}`, () => {
    const profile: Profile = structuredClone(corpus.valid[0]!.profile);
    profile.layer_2_resonance.modifiers[0]!.value = value;
    expect(() => validateGods(withProfile(profile))).toThrow(
      "veythar.layer_2_resonance.modifiers[0].value",
    );
  });
}
