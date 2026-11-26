import { expect, test } from "bun:test";
import corpus from "../../fixtures/god_profiles.json";
import roster from "../../../../content/archetypes.json";
import catalog from "../../../../content/gods.json";
import { validateGods } from "./index";

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

test("Orenthel's guardian and warrior have the registered wounded-ally clauses", () => {
  const matrix = validateGods(catalog).find(
    (god) => god.god_id === "orenthel",
  )?.layer_4_synergy_matrix;
  const condition =
    "while another conscious party member in this encounter is above 0 HP and below half their effective maximum HP.";
  for (const [archetype, name, benefit, implementation_id] of [
    ["guardian", "Sheltering Light", "Gain +1 AC", "orenthel_sheltering_light"],
    ["warrior", "Dawnward Strike", "Gain +1 damage against undead", "orenthel_dawnward_strike"],
  ] as const) {
    expect(matrix?.[archetype]).toEqual({
      type: "divine",
      name,
      clauses: [
        {
          effect: `${benefit} ${condition}`,
          status: "active",
          resolution: "engine",
          implementation_id,
        },
      ],
    });
  }
});
