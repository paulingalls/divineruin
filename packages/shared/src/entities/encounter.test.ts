import { test, expect, describe } from "bun:test";
import { TIER_LEVEL_RANGES, playerLevelRangeForTier, tierForPlayerLevel } from "./creature_tiers";
import {
  ENCOUNTER_ACTION_KIND_VALUES,
  ENCOUNTER_ROLE_VALUES,
  encounterActionKind,
  validateEncounterActionShape,
  validateEncounterActionKind,
  validateEncounterEnemyTier,
  type Encounter,
  type EncounterAction,
} from "./encounter";

const actionShapes = (await Bun.file(
  new URL("../../fixtures/enemy_action_shapes.json", import.meta.url),
).json()) as Record<string, Record<string, unknown>>;

const references = (await Bun.file(
  new URL("../../../../content/encounter_templates.json", import.meta.url),
).json()) as Encounter[];
const catalog = (await Bun.file(
  new URL("../../../../content/creatures.json", import.meta.url),
).json()) as {
  id: string;
  name: string;
  level: number;
  tier: number;
  ac: number;
  hp: number;
  xp_reward: number;
  attributes: Record<string, number>;
  signature_ability?: { name: string; description: string };
  attacks: (Omit<EncounterAction, "properties"> & { type: string; properties?: string[] })[];
  actives: (Omit<EncounterAction, "properties"> & { properties?: string[] })[];
}[];
const encounters = references.map((encounter) => ({
  ...encounter,
  enemies: encounter.enemies.map((reference) => {
    const row = catalog.find((row) => row.id === reference.creature_id);
    if (!row) throw new Error(reference.creature_id);
    const actions = [
      ...row.attacks,
      ...row.actives.filter((a) => a.kind && a.kind !== "attack"),
    ].map((a) => ({
      ...a,
      properties: [
        ...(a.properties ?? []),
        ...("type" in a && a.type === "ranged" ? ["ranged"] : []),
      ],
    }));
    return {
      ...row,
      ...reference,
      xp_value: row.xp_reward,
      signature_ability: reference.role === "boss" ? row.signature_ability : undefined,
      legendary_actions: reference.role === "boss" ? 1 : undefined,
      action_pool:
        reference.role === "minion"
          ? actions.filter((a) => !("recharge" in a) && (!a.kind || a.kind === "attack"))
          : actions,
    };
  }),
}));

describe("encounter_templates.json — encounter-role overlay", () => {
  test("catalog is non-empty", () => {
    expect(encounters.length).toBeGreaterThan(0);
  });

  test("every enemy carries a valid EncounterRole and the required stat fields", () => {
    for (const enc of encounters) {
      expect(Array.isArray(enc.enemies)).toBe(true);
      for (const enemy of enc.enemies) {
        expect(enemy.role).toBeDefined(); // content tags every enemy explicitly
        expect([...ENCOUNTER_ROLE_VALUES]).toContain(enemy.role);
        expect(typeof enemy.id).toBe("string");
        expect(typeof enemy.name).toBe("string");
        expect(typeof enemy.level).toBe("number");
        expect(typeof enemy.ac).toBe("number");
        expect(typeof enemy.hp).toBe("number");
        expect(typeof enemy.xp_value).toBe("number");
        expect(Array.isArray(enemy.action_pool)).toBe(true);
      }
    }
  });

  test("Bosses retain catalog signatures and one legendary action", () => {
    const bosses = encounters.flatMap((e) => e.enemies).filter((en) => en.role === "boss");
    expect(bosses.length).toBeGreaterThan(0); // at least one Boss exists to overlay
    expect(bosses.filter((boss) => boss.signature_ability)).toHaveLength(2);
    for (const boss of bosses) {
      const source = catalog.find((row) => row.id === boss.creature_id)!;
      expect(boss.signature_ability).toEqual(source.signature_ability);
      if (boss.signature_ability) {
        expect(typeof boss.signature_ability.name).toBe("string");
        expect(typeof boss.signature_ability.description).toBe("string");
      }
      expect(boss.legendary_actions).toBe(1);
    }
  });

  test("non-Boss enemies carry no signature ability or legendary actions", () => {
    for (const enemy of encounters.flatMap((e) => e.enemies)) {
      if (enemy.role !== "boss") {
        expect(enemy.signature_ability).toBeUndefined();
        expect(enemy.legendary_actions).toBeUndefined();
      }
    }
  });

  test("no encounter is all-Minion — Minions always have a non-Minion anchor (budget rule)", () => {
    for (const enc of encounters) {
      const hasMinion = enc.enemies.some((en) => en.role === "minion");
      if (hasMinion) {
        expect(enc.enemies.some((en) => en.role !== "minion")).toBe(true);
      }
    }
  });
});

describe("encounter_templates.json — enemy action kinds", () => {
  const actions = encounters.flatMap((enc) =>
    enc.enemies.flatMap((enemy) =>
      enemy.action_pool.map((action) => ({ encounterId: enc.id, enemyId: enemy.id, action })),
    ),
  );

  test("every action's kind is a known value", () => {
    for (const { action } of actions) {
      expect([...ENCOUNTER_ACTION_KIND_VALUES]).toContain(encounterActionKind(action));
      expect(() => validateEncounterActionShape(action)).not.toThrow();
    }
  });

  test("an unknown kind is refused", () => {
    expect(() => encounterActionKind({ name: "Decree", kind: "decree" })).toThrow("unknown kind");
  });

  test("catalog Lunge carriers author escape DC 13", () => {
    const carriers = actions
      .filter(({ action }) => action.properties.includes("grapple"))
      .map(({ enemyId, action }) => [
        enemyId,
        action.name,
        "escape_dc" in action ? action.escape_dc : undefined,
      ]);
    expect(carriers).toEqual([
      ["mawling_1", "Lunge", 13],
      ["mawling_2", "Lunge", 13],
      ["mawling_1", "Lunge", 13],
    ]);
  });

  test("a mark action carries no damage, damage type or applied condition", () => {
    const marks = actions.filter(({ action }) =>
      ["command", "accusation"].includes(encounterActionKind(action)),
    );
    expect(marks.length).toBe(4);
    for (const { action } of marks) {
      expect(Object.keys(action)).not.toContain("damage");
      expect(Object.keys(action)).not.toContain("damage_type");
      expect(Object.keys(action)).not.toContain("applies_condition");
    }
  });

  test("the five orders are the command carriers", () => {
    const carriers = actions
      .filter(({ action }) => encounterActionKind(action) === "command")
      .map(({ encounterId, enemyId, action }) => `${encounterId}/${enemyId}/${action.name}`);
    expect(carriers.sort()).toEqual([
      "ashmark_patrol/ashmark_sergeant/Rally",
      "cult_cell/cult_fanatic_1/Bless",
      "hollow_corrupted_settlement/hollowed_knight/Command Lesser",
    ]);
  });

  test("the Ashmark Sergeant is the one accusation carrier", () => {
    const carriers = actions
      .filter(({ action }) => encounterActionKind(action) === "accusation")
      .map(({ encounterId, enemyId, action }) => `${encounterId}/${enemyId}/${action.name}`);
    expect(carriers).toEqual(["ashmark_patrol/ashmark_sergeant/Accusation"]);
  });
});

describe("enemy action resolution shapes", () => {
  test.each(["valid_combined_bite", "valid_half_on_success", "corruption_wave"])(
    "%s is accepted",
    (fixtureName) => {
      expect(() => validateEncounterActionShape(actionShapes[fixtureName]!)).not.toThrow();
    },
  );

  test("half_on_success without save is refused", () => {
    expect(() => validateEncounterActionShape(actionShapes.invalid_half_without_save!)).toThrow(
      "save",
    );
  });

  // "0" is truthy in JS, so a naive falsiness check would wave this row through; the row carries a
  // valid save/dc, so only the damage check can throw here.
  test("half_on_success without damage is refused", () => {
    expect(() => validateEncounterActionShape(actionShapes.invalid_half_without_damage!)).toThrow(
      "half_on_success needs non-zero 'damage'",
    );
  });
});

describe("creature tier player bands", () => {
  test("the four spec ranges are exact", () => {
    expect(TIER_LEVEL_RANGES).toEqual({ 1: [1, 4], 2: [5, 8], 3: [9, 14], 4: [15, 20] });
    for (const [tier, band] of Object.entries(TIER_LEVEL_RANGES)) {
      expect(playerLevelRangeForTier(Number(tier))).toEqual(band);
    }
  });
  test("each level 1-20 belongs to exactly one tier", () => {
    for (let level = 1; level <= 20; level++) {
      const matches = Object.entries(TIER_LEVEL_RANGES)
        .filter(([, [low, high]]) => low <= level && level <= high)
        .map(([tier]) => Number(tier));
      expect(matches).toHaveLength(1);
      expect(tierForPlayerLevel(level)).toBe(matches[0]!);
    }
  });
  test.each([0, 5])("invalid tier %i fails", (tier) => {
    expect(() => playerLevelRangeForTier(tier)).toThrow();
  });
  test.each([0, 21, -1])("level %i fails", (level) => {
    expect(() => tierForPlayerLevel(level)).toThrow();
  });
});

describe("authored creature tiers", () => {
  test("every content row has the expected tier", () => {
    const rows = encounters.flatMap((enc) => enc.enemies.map((enemy) => [enc.id, enemy] as const));
    expect(rows).toHaveLength(26);
    const named: Record<string, number> = {
      Shadeling: 1,
      Mawling: 2,
      "Hollowed Knight": 3,
      "Cult Fanatic": 1,
    };
    for (const [encId, enemy] of rows) {
      expect(() => validateEncounterEnemyTier(encId, enemy)).not.toThrow();
      expect(enemy.tier).toBe(named[enemy.name] ?? tierForPlayerLevel(enemy.level));
    }
    for (const name of Object.keys(named)) {
      expect(rows.filter(([, enemy]) => enemy.name === name).length).toBeGreaterThan(0);
    }
  });
  test.each([undefined, 0, 5, 1.5, "2"])("rejects tier %p with row identity", (tier) => {
    expect(() => validateEncounterEnemyTier("bad_encounter", { id: "bad_enemy", tier })).toThrow(
      /bad_encounter.*bad_enemy/,
    );
  });
});

const contractCorpus = (await Bun.file(
  new URL("../../fixtures/creature_blocks.json", import.meta.url),
).json()) as {
  valid: {
    name: string;
    block: { actives: Record<string, unknown>[]; attacks: Record<string, unknown>[] };
  }[];
  invalid: {
    name: string;
    field?: string;
    block: { actives: Record<string, unknown>[]; attacks: Record<string, unknown>[] };
  }[];
};
for (const row of contractCorpus.valid.filter((r) =>
  /^(recharge_|advantage_|active_)/.test(r.name),
))
  test(`structured_recharge action_advantage active_contract ${row.name}`, () => {
    for (const action of row.block.actives.length ? row.block.actives : row.block.attacks) {
      expect(() => validateEncounterActionShape(action)).not.toThrow();
      expect(() => validateEncounterActionKind(action, "enemy 'fixture'")).not.toThrow();
    }
  });
for (const row of contractCorpus.invalid.filter(
  (r) =>
    /^(recharge_|advantage_|active_healing_|active_prepare_attack_|mark_)/.test(r.name) ||
    (r.name.startsWith("active_attack_") && r.name.includes("_type_")),
))
  test(`structured_recharge action_advantage active_contract rejection ${row.name}`, () => {
    const actions = row.block.actives.length ? row.block.actives : row.block.attacks;
    expect(() => {
      for (const action of actions) {
        validateEncounterActionShape(action);
        validateEncounterActionKind(action, "enemy 'fixture'");
      }
    }).toThrow(row.field);
  });

const catalogAction = {
  name: "Bite",
  attack_source: "catalog",
  to_hit: 9,
  damage: "1d8+2",
  damage_type: "piercing",
  properties: [],
};
test("catalog runtime extensions pass the public encounter boundary", () => {
  expect(() => validateEncounterActionShape(catalogAction, "catalog")).not.toThrow();
  for (const [field, value] of [
    ["attack_source", "unknown"],
    ["to_hit", true],
    ["to_hit", undefined],
    ["self_heal", "raw_damage"],
  ]) {
    expect(() =>
      validateEncounterActionShape({ ...catalogAction, [field as string]: value }, "catalog"),
    ).toThrow(field);
  }
});

test("catalog runtime extensions reject contradictory action shapes", () => {
  const rally = { name: "Rally", kind: "healing", target_group: "allied_bandits", healing: "1d8" };
  expect(() =>
    validateEncounterActionShape({ ...rally, attack_source: "catalog" }, "catalog"),
  ).toThrow("attack_source");
  expect(() =>
    validateEncounterActionShape({ ...rally, self_heal: "damage_dealt" }, "catalog"),
  ).toThrow("self_heal");
  expect(() =>
    validateEncounterActionShape(
      {
        name: "Blind",
        kind: "attack",
        damage: "0",
        damage_type: "none",
        applies_condition: "blinded",
        save: "constitution",
        dc: 12,
        self_heal: "damage_dealt",
      },
      "catalog",
    ),
  ).toThrow("self_heal");
});
