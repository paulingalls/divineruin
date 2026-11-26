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
