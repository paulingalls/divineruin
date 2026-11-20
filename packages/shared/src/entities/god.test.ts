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
    mark,
    veilstep,
    gateway,
    walk,
    wrath,
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
  expect(pending).toHaveLength(9);
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

test("the authored critical synergies are active engine clauses", () => {
  const gods = validateGods(catalog);
  for (const [patron, archetype, type, implementation_id] of [
    ["zhael", "rogue", "divine", "zhael_bent_probability"],
    ["zhael", "mage", "divine", "zhael_bent_probability"],
    ["thyra", "warrior", "unexpected", "thyra_natures_edge"],
    ["thyra", "skirmisher", "unexpected", "thyra_natures_edge"],
  ] as const) {
    const god = gods.find((entry) => entry.god_id === patron);
    expect(god?.layer_4_synergy_matrix[archetype]).toMatchObject({
      type,
      clauses: [{ status: "active", resolution: "engine", implementation_id }],
    });
  }
});

test("Kaelen's Natural synergies have both active engine clauses", () => {
  const kaelen = validateGods(catalog).find((god) => god.god_id === "kaelen");
  const natural = Object.entries(kaelen!.layer_4_synergy_matrix).filter(
    ([, row]) => row.type === "natural",
  );
  expect(natural.map(([archetype]) => archetype).sort()).toEqual([
    "guardian",
    "skirmisher",
    "warrior",
  ]);
  for (const [, row] of natural) {
    expect(row.clauses).toHaveLength(2);
    expect(row.clauses).toMatchObject(
      ["kaelen_tempered_resolve", "kaelen_extra_attack_damage"].map((implementation_id) => ({
        status: "active",
        resolution: "engine",
        implementation_id,
      })),
    );
  }
});

test("the authored spell synergies activate five engine clauses", () => {
  const gods = validateGods(catalog);
  for (const [patron, archetype, type, implementation_id] of [
    ["veythar", "mage", "natural", "veythar_simplest_mysteries"],
    ["veythar", "artificer", "natural", "veythar_simplest_mysteries"],
    ["veythar", "seeker", "natural", "veythar_simplest_mysteries"],
    ["mortaen", "mage", "divine", "mortaen_ashen_formula"],
    ["mortaen", "cleric", "natural", "mortaen_threshold_mercy"],
  ] as const) {
    const god = gods.find((entry) => entry.god_id === patron);
    const row = god?.layer_4_synergy_matrix[archetype];
    expect(row?.type).toBe(type);
    expect(row?.clauses).toHaveLength(archetype === "cleric" ? 2 : 1);
    expect(row?.clauses[0]).toMatchObject({
      status: "active",
      resolution: "engine",
      implementation_id,
    });
  }
});

test("Orenthel's Natural healing synergies are active engine clauses", () => {
  const orenthel = validateGods(catalog).find((god) => god.god_id === "orenthel");
  for (const archetype of ["cleric", "paladin"] as const) {
    const row = orenthel?.layer_4_synergy_matrix[archetype];
    expect(row?.type).toBe("natural");
    expect(row?.clauses).toHaveLength(1);
    expect(row?.clauses[0]).toMatchObject({
      status: "active",
      resolution: "engine",
      implementation_id: "orenthel_dawns_mercy",
    });
  }
});

test("Mortaen's cleric and paladin healing clauses are active engine clauses", () => {
  const mortaen = validateGods(catalog).find((god) => god.god_id === "mortaen");
  const cleric = mortaen?.layer_4_synergy_matrix.cleric;
  const paladin = mortaen?.layer_4_synergy_matrix.paladin;
  const active = { status: "active", resolution: "engine" } as const;
  expect(cleric?.type).toBe("natural");
  expect(cleric?.clauses).toEqual([
    {
      ...active,
      effect: "Sacred Flame deals necrotic.",
      implementation_id: "mortaen_threshold_mercy",
    },
    {
      ...active,
      effect: "Healing on 0 HP allies restores double. Best at pulling people back from the edge",
      implementation_id: "mortaen_threshold_healing",
    },
  ]);
  expect(paladin?.type).toBe("divine");
  expect(paladin?.clauses).toEqual([
    {
      ...active,
      effect: "Healing an ally at 0 HP restores 1 additional HP.",
      implementation_id: "mortaen_final_mercy",
    },
  ]);
});

test.each([
  ["thyra", "Verdant Healing", "Healing in natural terrain +1d4 extra HP", "thyra_verdant_healing"],
  [
    "nythera",
    "Traveler's Blessing",
    "Healing a creature in an unexplored location restores 1 additional HP.",
    "nythera_travelers_blessing",
  ],
])("%s has an active engine clause for place-based cleric healing", (patron, name, effect, id) => {
  const god = validateGods(catalog).find((god) => god.god_id === patron);
  expect(god?.layer_4_synergy_matrix.cleric).toEqual({
    type: "divine",
    name,
    clauses: [{ effect, status: "active", resolution: "engine", implementation_id: id }],
  });
});

test.each([
  ["mortaen", "mortaen_last_vigil"],
  ["zhael", "zhael_threaded_blade"],
])("%s has an active engine clause for encounter damage", (patron, id) => {
  const warrior = validateGods(catalog).find((god) => god.god_id === patron)?.layer_4_synergy_matrix
    .warrior;
  expect(warrior?.type).toBe("divine");
  expect(warrior?.clauses).toHaveLength(1);
  expect(warrior?.clauses[0]).toMatchObject({
    status: "active",
    resolution: "engine",
    implementation_id: id,
  });
});

test("Kaelen's Oath of Valor is an active paladin engine clause", () => {
  const kaelen = validateGods(catalog).find((god) => god.god_id === "kaelen");
  expect(kaelen?.layer_4_synergy_matrix.paladin).toEqual({
    type: "divine",
    name: "Oath of Valor",
    clauses: [
      {
        effect: "Oath of Valor: sworn strikes deal +1d6 radiant vs foes that outnumber the party",
        status: "active",
        resolution: "engine",
        implementation_id: "kaelen_oath_of_valor",
      },
    ],
  });
});

test("Zhael's Second Before is an active guardian engine clause", () => {
  const zhael = validateGods(catalog).find((god) => god.god_id === "zhael");
  expect(zhael?.layer_4_synergy_matrix.guardian).toEqual({
    type: "divine",
    name: "Second Before",
    clauses: [
      {
        effect: "Gain +1 AC against the first attack made against you each encounter.",
        status: "active",
        resolution: "engine",
        implementation_id: "zhael_second_before",
      },
    ],
  });
});

test("Zhael's Appointed Mercy is an active cleric engine clause", () => {
  const zhael = validateGods(catalog).find((god) => god.god_id === "zhael");
  expect(zhael?.layer_4_synergy_matrix.cleric).toEqual({
    type: "divine",
    name: "Appointed Mercy",
    clauses: [
      {
        effect:
          "Healing an ally who succeeded on a death saving throw this round restores 1 additional HP.",
        status: "active",
        resolution: "engine",
        implementation_id: "zhael_appointed_mercy",
      },
    ],
  });
});

test.each(["druid", "warden"] as const)(
  "Mortaen's %s renews Focus through the engine",
  (archetype) => {
    const row = validateGods(catalog).find((god) => god.god_id === "mortaen")
      ?.layer_4_synergy_matrix[archetype];
    expect(row).toMatchObject({ type: "divine", name: "Death Feeds Renewal" });
    expect(row?.clauses).toHaveLength(1);
    expect(row?.clauses[0]).toMatchObject({
      status: "active",
      resolution: "engine",
      implementation_id: "mortaen_death_feeds_renewal",
    });
  },
);
