import { test, expect, describe } from "bun:test";
import {
  ENCOUNTER_ACTION_KIND_VALUES,
  ENCOUNTER_ROLE_VALUES,
  encounterActionKind,
  type Encounter,
} from "./encounter";

// Conformance test for content/encounter_templates.json (Phase 4 M4.7 / story-001). The JSON row
// IS the cross-language contract apps/agent/combat_init.py parses to build CombatParticipants; this
// test guards the role overlay's shape independent of that loader and serves as the compile-time
// shape check for the Encounter type (rows are cast to Encounter, so interface drift breaks
// `tsc --noEmit` / `bun test`).

const encounters = (await Bun.file(
  new URL("../../../../content/encounter_templates.json", import.meta.url),
).json()) as Encounter[];

describe("encounter_templates.json — encounter-role overlay", () => {
  test("catalog is non-empty", () => {
    expect(encounters.length).toBeGreaterThan(0);
  });

  test("every enemy carries a valid EncounterRole and the required stat fields", () => {
    for (const enc of encounters) {
      expect(Array.isArray(enc.enemies)).toBe(true);
      for (const enemy of enc.enemies) {
        expect(enemy.role).toBeDefined(); // content tags every enemy explicitly
        expect([...ENCOUNTER_ROLE_VALUES]).toContain(enemy.role!);
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

  test("every Boss authors a signature ability and one legendary action", () => {
    const bosses = encounters.flatMap((e) => e.enemies).filter((en) => en.role === "boss");
    expect(bosses.length).toBeGreaterThan(0); // at least one Boss exists to overlay
    for (const boss of bosses) {
      expect(boss.signature_ability).toBeDefined();
      expect(typeof boss.signature_ability!.name).toBe("string");
      expect(typeof boss.signature_ability!.description).toBe("string");
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

// The action `kind` is mirrored from apps/agent/encounter_actions.py (constraint 7): absent means
// "attack", and every other kind is a mark action that never rolls, so it carries no strike fields.
describe("encounter_templates.json — enemy action kinds", () => {
  const actions = encounters.flatMap((enc) =>
    enc.enemies.flatMap((enemy) =>
      enemy.action_pool.map((action) => ({ encounterId: enc.id, enemyId: enemy.id, action })),
    ),
  );

  test("every action's kind is a known value", () => {
    for (const { action } of actions) {
      expect([...ENCOUNTER_ACTION_KIND_VALUES]).toContain(encounterActionKind(action));
    }
  });

  test("an unknown kind is refused", () => {
    expect(() => encounterActionKind({ name: "Decree", kind: "decree" })).toThrow("unknown kind");
  });

  test("a mark action carries no damage, damage type or applied condition", () => {
    const marks = actions.filter(({ action }) => encounterActionKind(action) !== "attack");
    expect(marks.length).toBe(6);
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
      "bandit_ambush/bandit_captain/Press the Attack",
      "cult_cell/cult_fanatic_1/Bless",
      "cult_cell/cult_fanatic_2/Bless",
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
