import { expect, test } from "bun:test";
import corpus from "../../fixtures/god_profiles.json";
import roster from "../../../../content/archetypes.json";
import catalog from "../../../../content/gods.json";
import { type GodSynergyClause, validateGods } from "./index";

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

test("Orenthel's guardian has the registered Sheltering Light clause", () => {
  const guardian = validateGods(catalog).find((god) => god.god_id === "orenthel")
    ?.layer_4_synergy_matrix.guardian;
  expect(guardian?.name).toBe("Sheltering Light");
  expect(guardian?.type).toBe("divine");
  expect(guardian?.clauses).toEqual([
    {
      effect: "Gain +1 AC while guarding an ally below half HP.",
      status: "active",
      resolution: "engine",
      implementation_id: "orenthel_guardian_ward",
    },
  ]);
});

test.each(["cleric", "oracle"] as const)("Valdris's %s has Absolute Authority", (archetype) => {
  const valdris = validateGods(catalog).find((god) => god.god_id === "valdris");
  expect(valdris?.layer_4_synergy_matrix[archetype]).toEqual({
    name: "Absolute Authority",
    type: "divine",
    clauses: [
      {
        effect: "Turn Undead/Hollow DC +1. Absolute authority against unnatural things",
        status: "active",
        resolution: "engine",
        implementation_id: "valdris_absolute_authority",
      },
    ],
  });
});

test("Orenthel's warrior has the registered Dawnward Strike clause", () => {
  const warrior = validateGods(catalog).find((god) => god.god_id === "orenthel")
    ?.layer_4_synergy_matrix.warrior;
  expect(warrior?.name).toBe("Dawnward Strike");
  expect(warrior?.type).toBe("divine");
  expect(warrior?.clauses).toEqual([
    {
      effect: "Gain +1 damage against undead while an ally within earshot is below half HP.",
      status: "active",
      resolution: "engine",
      implementation_id: "orenthel_undead_wrath",
    },
  ]);
});

test("Nythera's mage has the registered Saltwind Casting clause", () => {
  const mage = validateGods(catalog).find((god) => god.god_id === "nythera")?.layer_4_synergy_matrix
    .mage;
  expect(mage).toEqual({
    name: "Saltwind Casting",
    type: "divine",
    clauses: [
      {
        effect: "Gain +1 to spell attack rolls in a coastal location you have never visited.",
        status: "active",
        resolution: "engine",
        implementation_id: "nythera_saltwind_casting",
      },
    ],
  });
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

test("Zhael's marshal has the registered Moment to Rally clause", () => {
  const marshal = validateGods(catalog).find((god) => god.god_id === "zhael")
    ?.layer_4_synergy_matrix.marshal;
  expect(marshal).toEqual({
    name: "Moment to Rally",
    type: "divine",
    clauses: [
      {
        effect:
          "Once per encounter, an ally who follows your order gains +1 on their next saving throw.",
        status: "active",
        resolution: "engine",
        implementation_id: "zhael_moment_to_rally",
      },
    ],
  });
});

test("Zhael's bard and diplomat have the registered Foretold Words clause", () => {
  const matrix = validateGods(catalog).find(
    (god) => god.god_id === "zhael",
  )?.layer_4_synergy_matrix;
  for (const archetype of ["bard", "diplomat"] as const) {
    expect(matrix?.[archetype]).toEqual({
      name: "Foretold Words",
      type: "unexpected",
      clauses: [
        {
          effect:
            "Social encounters: once per NPC per session, know the exact DC of the next social check before attempting",
          status: "active",
          resolution: "engine",
          implementation_id: "zhael_foretold_words",
        },
      ],
    });
  }
});

for (const entry of corpus.context_clause_cases) {
  test(`context profile: ${entry.id}`, () => {
    const profile = structuredClone(corpus.valid[0]!.profile);
    const clause = profile.layer_4_synergy_matrix.cleric.clauses[0]!;
    const context: Record<string, unknown> = {
      ...clause,
      ...corpus.context_clause,
      ...("set" in entry ? entry.set : {}),
    };
    for (const key of "remove" in entry ? (entry.remove ?? []) : []) delete context[key];
    Object.assign(clause, context);
    const rows = [profile, ...catalog.slice(1)];
    if ("field" in entry) {
      expect(() => validateGods(rows)).toThrow(
        `veythar.layer_4_synergy_matrix.cleric.clauses[0].${entry.field}:`,
      );
    } else {
      expect(Object.is(validateGods(rows), rows)).toBe(true);
    }
  });
}

test.each([
  [
    "aelora",
    "cleric",
    "divine",
    "Shared Table",
    "shared_meal",
    "religion",
    "aelora_shared_table",
    "Gain +1 Religion when blessing a shared meal.",
  ],
  [
    "aelora",
    "paladin",
    "divine",
    "Civic Promise",
    "community_duties",
    "persuasion",
    "aelora_civic_promise",
    "Gain +1 Persuasion when negotiating a community’s shared duties.",
  ],
  [
    "aelora",
    "oracle",
    "divine",
    "Hearth Omen",
    "household_omen",
    "insight",
    "aelora_hearth_omen",
    "Gain +1 Insight when interpreting a household omen.",
  ],
  [
    "aelora",
    "rogue",
    "unexpected",
    "Honest Hustle",
    "commerce",
    "persuasion",
    "aelora_commerce_persuasion",
    "Commerce Persuasion +1.",
  ],
  [
    "thyra",
    "paladin",
    "divine",
    "Wild Covenant",
    "sacred_grove",
    "religion",
    "thyra_wild_covenant",
    "Gain +1 Religion when honoring a sacred grove.",
  ],
  [
    "thyra",
    "oracle",
    "divine",
    "Seasonal Omen",
    "seasonal_omen",
    "nature",
    "thyra_seasonal_omen",
    "Gain +1 Nature when interpreting a seasonal omen.",
  ],
  [
    "nythera",
    "warden",
    "divine",
    "Shoreline Keeper",
    "coast_shelter",
    "survival",
    "nythera_shoreline_keeper",
    "Gain +1 Survival when finding safe shelter along an unfamiliar coast.",
  ],
  [
    "nythera",
    "diplomat",
    "divine",
    "Harbor Courtesy",
    "port_passage",
    "persuasion",
    "nythera_harbor_courtesy",
    "Gain +1 Persuasion when seeking peaceful passage through an unfamiliar port.",
  ],
  [
    "nythera",
    "artificer",
    "divine",
    "Voyager's Tools",
    "vessel_repair",
    null,
    "nythera_voyagers_tools",
    "Gain +1 to checks to repair a vessel during a journey.",
  ],
  [
    "orenthel",
    "artificer",
    "divine",
    "Mender's Dawn",
    "sanctuary_repair",
    null,
    "orenthel_menders_dawn",
    "Gain +1 to checks to repair equipment for a damaged sanctuary.",
  ],
  [
    "orenthel",
    "warden",
    "divine",
    "Green Morning",
    "blighted_grove",
    "nature",
    "orenthel_green_morning",
    "Gain +1 Nature when restoring a blighted grove.",
  ],
  [
    "orenthel",
    "diplomat",
    "divine",
    "Reconciliation",
    "wounded_enemy_care",
    "persuasion",
    "orenthel_reconciliation",
    "Gain +1 Persuasion when negotiating care for wounded enemies.",
  ],
  [
    "valdris",
    "mage",
    "divine",
    "Ordered Testimony",
    "broken_oath_evidence",
    "arcana",
    "valdris_oathbreak_sight",
    "Gain +1 Arcana when examining magical evidence of a broken oath.",
  ],
  [
    "valdris",
    "artificer",
    "divine",
    "Honest Measure",
    "tampered_measures",
    "investigation",
    "valdris_true_measure",
    "Gain +1 Investigation when examining tampered scales or measuring tools.",
  ],
  [
    "valdris",
    "seeker",
    "divine",
    "Chain of Evidence",
    "evidence_ownership_hearing",
    "investigation",
    "valdris_chain_of_custody",
    "Gain +1 Investigation when tracing ownership of evidence in a public hearing.",
  ],
  [
    "valdris",
    "warden",
    "divine",
    "Common Ground",
    "unlawful_incursion",
    "survival",
    "valdris_boundary_law",
    "Gain +1 Survival when tracing an unlawful incursion into protected land.",
  ],
  [
    "valdris",
    "diplomat",
    "divine",
    "Fair Terms",
    "equal_terms_petition",
    "persuasion",
    "valdris_even_scales",
    "Gain +1 Persuasion when securing equal terms for opposing petitioners.",
  ],
  [
    "valdris",
    "rogue",
    "unexpected",
    "Truth in Disguise",
    "just_cause_deception",
    "deception",
    "valdris_just_deceit",
    "Deception for just causes (evidence, infiltration) gains +1. Valdris blesses deception in service of truth",
  ],
  [
    "valdris",
    "spy",
    "unexpected",
    "Truth in Disguise",
    "just_cause_deception",
    "deception",
    "valdris_just_deceit",
    "Deception for just causes (evidence, infiltration) gains +1. Valdris blesses deception in service of truth",
  ],
] as const)(
  "%s %s has the registered context clause",
  (patron, archetype, type, name, tag, skill, implementation, effect) => {
    const matrix = validateGods(catalog).find(
      (god) => god.god_id === patron,
    )?.layer_4_synergy_matrix;
    const clauses: GodSynergyClause[] = [
      {
        effect,
        kind: "context_check",
        synergy_context: tag,
        skill,
        bonus: 1,
        status: "active",
        resolution: "engine",
        implementation_id: implementation,
      },
    ];
    if (patron === "aelora" && archetype === "rogue") {
      clauses.push({
        effect: "Better fence prices. Aelora respects the hustle",
        status: "pending",
        resolution: "engine",
      });
    }
    expect(matrix?.[archetype]).toEqual({ name, type, clauses });
  },
);
