import { test, expect, describe } from "bun:test";
import { ENCOUNTER_ROLE_VALUES, type Encounter } from "./encounter";

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
