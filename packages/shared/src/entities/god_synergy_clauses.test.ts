import { expect, test } from "bun:test";
import catalog from "../../../../content/gods.json";
import { validateGods } from "./index";

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
