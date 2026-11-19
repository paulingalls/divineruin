import { expect, test } from "bun:test";
import corpus from "../../fixtures/god_profiles.json";
import roster from "../../../../content/archetypes.json";
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
  for (const [patron, id] of [
    ["mortaen", "mortaen_deaths_awareness"],
    ["nythera", "nythera_horizon_sense"],
  ]) {
    expect(validateGods(catalog).find((god) => god.god_id === patron)?.layer_1_gift).toMatchObject({
      id,
      status: "active",
      resolution: "engine",
      implementation_id: id,
    });
  }
  expect(validateGods(catalog).find((god) => god.god_id === "zhael")?.layer_1_gift).toMatchObject({
    id: "zhael_fates_thread",
    status: "active",
    recharge: "long_rest",
    resolution: "engine",
    implementation_id: "zhael_fates_thread",
  });
  expect(validateGods(catalog).find((god) => god.god_id === "syrath")?.layer_1_gift).toMatchObject({
    id: "syrath_shadow_veil",
    status: "active",
    recharge: "short_rest",
  });
  expect(validateGods(catalog).find((god) => god.god_id === "valdris")?.layer_1_gift).toMatchObject(
    {
      id: "valdris_weight_of_truth",
      status: "active",
      recharge: "short_rest",
    },
  );
  const narrated = new Set([
    "veythar_lorekeepers_library",
    "syrath_whisper_network",
    "syrath_the_veilwatchers_eye",
    "mortaen_speak_with_dead",
    "nythera_charted_course",
    "valdris_discern_lies",
    "zhael_prophecy_fragment",
  ]);
  const abilities = validateGods(catalog).flatMap((god) => {
    expect(Object.keys(god.layer_3_tier_abilities).sort()).toEqual([
      "acknowledged",
      "devoted",
      "exalted",
    ]);
    return Object.values(god.layer_3_tier_abilities);
  });
  expect(abilities).toHaveLength(30);
  expect(new Set(abilities.map((a) => a.id)).size).toBe(30);
  expect(
    new Set(
      abilities
        .filter((a) => a.status === "active" && a.resolution === "narrated")
        .map((a) => a.id),
    ),
  ).toEqual(narrated);
  const passives = new Set(["veythar_scholars_ward", "kaelen_warriors_endurance"]);
  const engine = new Set(["zhael_lucky", ...passives]);
  expect(
    new Set(
      abilities.filter((a) => a.status === "active" && a.resolution === "engine").map((a) => a.id),
    ),
  ).toEqual(engine);
  const pending = abilities.filter((a) => !narrated.has(a.id) && !engine.has(a.id));
  expect(pending).toHaveLength(20);
  for (const ability of abilities.filter((a) => passives.has(a.id))) {
    expect([ability.recharge, ability.implementation_id]).toEqual(["always", ability.id]);
  }
  for (const ability of pending)
    expect([ability.status, ability.resolution]).toEqual(["pending", "engine"]);
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
      `${entry.patron}.${entry.field}:`,
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

test("ten complete matrices cover the exact eighteen-archetype roster", () => {
  const gods = validateGods(catalog);
  expect(gods.map((g) => g.god_id).sort()).toEqual([...corpus.patron_ids].sort());
  expect(roster).toHaveLength(18);
  expect(new Set(roster.map((a) => a.id)).size).toBe(18);
  for (const god of gods) {
    expect(god.layer_4_synergy_matrix).not.toBeNull();
    expect(Object.keys(god.layer_4_synergy_matrix).sort()).toEqual(roster.map((a) => a.id).sort());
  }
  expect(gods.reduce((sum, god) => sum + Object.keys(god.layer_4_synergy_matrix).length, 0)).toBe(
    180,
  );
});

for (const entry of corpus.layer_1_cases) {
  test(`Layer 1 profile: ${entry.id}`, () => {
    const profile = structuredClone(corpus.valid[0]!.profile);
    const gift: Record<string, unknown> = { ...profile.layer_1_gift, ...entry.set };
    if (entry.delete) delete gift[entry.delete];
    const rows = withProfile({ ...profile, layer_1_gift: gift });
    if (entry.field) {
      expect(() => validateGods(rows)).toThrow(`veythar.layer_1_gift.${entry.field}:`);
    } else {
      expect(Object.is(validateGods(rows), rows)).toBe(true);
    }
  });
}
