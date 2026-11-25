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
    ["orenthel", "orenthel_dawns_resilience"],
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
  const passives = new Set([
    "veythar_scholars_ward",
    "kaelen_warriors_endurance",
    "orenthel_beacon",
  ]);
  const battleCry = "kaelen_battle_cry_of_the_ironhand";
  const judgment = "kaelen_kaelens_judgment";
  const surge = "orenthel_restoration_surge";
  expect(
    validateGods(catalog).find((god) => god.god_id === "orenthel")?.layer_3_tier_abilities.devoted,
  ).toMatchObject({
    id: surge,
    status: "active",
    resolution: "engine",
    implementation_id: surge,
    recharge: "long_rest",
  });
  const shield = "aelora_community_shield";
  expect(
    validateGods(catalog).find((god) => god.god_id === "aelora")?.layer_3_tier_abilities.devoted,
  ).toMatchObject({
    id: shield,
    status: "active",
    resolution: "engine",
    implementation_id: shield,
    recharge: "long_rest",
  });
  const mark = "valdris_mark_of_justice";
  expect(
    validateGods(catalog).find((god) => god.god_id === "valdris")?.layer_3_tier_abilities.devoted,
  ).toMatchObject({
    id: mark,
    status: "active",
    resolution: "engine",
    implementation_id: mark,
    recharge: "long_rest",
  });
  const veilstep = "syrath_veilstep";
  expect(
    validateGods(catalog).find((god) => god.god_id === "syrath")?.layer_3_tier_abilities.devoted,
  ).toMatchObject({
    id: veilstep,
    status: "active",
    resolution: "engine",
    implementation_id: veilstep,
    recharge: "long_rest",
  });
  const gateway = "nythera_beyond_the_horizon";
  expect(
    catalog.find((god) => god.god_id === "nythera")?.layer_3_tier_abilities.exalted,
  ).toMatchObject({
    id: gateway,
    status: "active",
    resolution: "engine",
    implementation_id: gateway,
    recharge: "per_session",
  });
  const walk = "mortaen_threshold_walk";
  expect(
    validateGods(catalog).find((god) => god.god_id === "mortaen")?.layer_3_tier_abilities.exalted,
  ).toMatchObject({
    id: walk,
    status: "active",
    resolution: "engine",
    implementation_id: walk,
    recharge: "per_session",
  });
  const thornwall = "thyra_thornwall";
  expect(
    validateGods(catalog).find((god) => god.god_id === "thyra")?.layer_3_tier_abilities.devoted,
  ).toMatchObject({
    id: thornwall,
    status: "active",
    resolution: "engine",
    implementation_id: thornwall,
    recharge: "long_rest",
  });
  const wrath = "thyra_wildmothers_wrath";
  expect(
    validateGods(catalog).find((god) => god.god_id === "thyra")?.layer_3_tier_abilities.exalted,
  ).toMatchObject({
    id: wrath,
    status: "active",
    resolution: "engine",
    implementation_id: wrath,
    recharge: "per_session",
  });
  const verdict = "valdris_the_scales_verdict";
  expect(
    validateGods(catalog).find((god) => god.god_id === "valdris")?.layer_3_tier_abilities.exalted,
  ).toMatchObject({
    id: verdict,
    status: "active",
    resolution: "engine",
    implementation_id: verdict,
    recharge: "per_session",
  });
  const ward = "mortaen_death_ward";
  expect(
    validateGods(catalog).find((god) => god.god_id === "mortaen")?.layer_3_tier_abilities
      .acknowledged,
  ).toMatchObject({
    id: ward,
    status: "active",
    resolution: "engine",
    implementation_id: ward,
    recharge: "long_rest",
  });
  const embrace = "orenthel_dawns_embrace";
  expect(
    validateGods(catalog).find((god) => god.god_id === "orenthel")?.layer_3_tier_abilities.exalted,
  ).toMatchObject({
    id: embrace,
    status: "active",
    resolution: "engine",
    implementation_id: embrace,
    recharge: "per_session",
  });
  const engine = new Set([
    "zhael_lucky",
    battleCry,
    judgment,
    surge,
    shield,
    mark,
    veilstep,
    gateway,
    walk,
    wrath,
    thornwall,
    verdict,
    ward,
    embrace,
    ...passives,
  ]);
  expect(
    new Set(
      abilities.filter((a) => a.status === "active" && a.resolution === "engine").map((a) => a.id),
    ),
  ).toEqual(engine);
  const pending = abilities.filter((a) => !narrated.has(a.id) && !engine.has(a.id));
  expect(pending).toHaveLength(6);
  for (const ability of abilities.filter((a) => passives.has(a.id))) {
    expect([ability.recharge, ability.implementation_id]).toEqual(["always", ability.id]);
  }
  const cry = abilities.find((a) => a.id === battleCry);
  expect([cry?.recharge, cry?.implementation_id]).toEqual(["long_rest", battleCry]);
  const worthyFoe = abilities.find((a) => a.id === judgment);
  expect([worthyFoe?.recharge, worthyFoe?.implementation_id]).toEqual(["per_session", judgment]);
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

test("Mortaen's guardian has the registered Threshold Shield clause", () => {
  const guardian = validateGods(catalog).find((god) => god.god_id === "mortaen")
    ?.layer_4_synergy_matrix.guardian;
  expect(guardian).toMatchObject({
    name: "Threshold Shield",
    type: "divine",
    clauses: [
      { status: "active", resolution: "engine", implementation_id: "mortaen_threshold_shield" },
    ],
  });
  expect(guardian?.clauses).toHaveLength(1);
});

test("Mortaen's marshal has the registered Hold the Crossing clause", () => {
  const marshal = validateGods(catalog).find((god) => god.god_id === "mortaen")
    ?.layer_4_synergy_matrix.marshal;
  expect(marshal).toMatchObject({
    name: "Hold the Crossing",
    type: "divine",
    clauses: [
      {
        effect: "Allies at 0 HP within earshot gain +1 to death saving throws.",
        status: "active",
        resolution: "engine",
        implementation_id: "mortaen_hold_the_crossing",
      },
    ],
  });
  expect(marshal?.clauses).toHaveLength(1);
});

test("Kaelen's bard has the registered War Songs clause", () => {
  const bard = validateGods(catalog).find((god) => god.god_id === "kaelen")?.layer_4_synergy_matrix
    .bard;
  expect(bard).toMatchObject({
    name: "War Songs",
    type: "unexpected",
    clauses: [{ status: "active", resolution: "engine", implementation_id: "kaelen_war_songs" }],
  });
  expect(bard?.clauses).toHaveLength(1);
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

test("Syrath's Shadow Veil duration and strike are registered for rogue, spy and whisper", () => {
  const matrix = validateGods(catalog).find(
    (god) => god.god_id === "syrath",
  )?.layer_4_synergy_matrix;
  for (const archetype of ["rogue", "spy", "whisper"] as const) {
    expect(matrix?.[archetype]?.clauses).toEqual([
      {
        effect: "Shadow Veil extends to 2 rounds.",
        status: "active",
        resolution: "engine",
        implementation_id: "syrath_two_round_veil",
      },
      {
        effect:
          archetype === "rogue"
            ? "Invisible Sneak Attack +1d6"
            : "Weapon attacks from Shadow Veil deal +1d6",
        status: "active",
        resolution: "engine",
        implementation_id: "syrath_veiled_strike",
      },
    ]);
  }
});

test("Zhael's oracle has both Woven Prophecy clauses", () => {
  const matrix = validateGods(catalog).find(
    (god) => god.god_id === "zhael",
  )?.layer_4_synergy_matrix;
  expect(matrix?.oracle).toEqual({
    type: "natural",
    name: "Woven Prophecy",
    clauses: [
      {
        effect: "Prophecy Fragment becomes 2-sentence vision with more detail.",
        status: "active",
        resolution: "narrated",
      },
      {
        effect: "Fate's Thread usable twice per long rest",
        status: "active",
        resolution: "engine",
        implementation_id: "zhael_twice_woven",
      },
    ],
  });
});
