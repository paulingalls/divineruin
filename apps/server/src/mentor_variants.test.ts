import { test, expect, describe, afterAll } from "bun:test";
import {
  parseMentorVariantRow,
  getMentorVariant,
  getVariant,
  getVariantsForAbility,
  setMentorVariants,
} from "./mentor_variants.ts";
import type { MentorVariant } from "@divineruin/shared";

// Drives the production fail-loud parseMentorVariantRow over inline fixtures and
// pins the accessors, mirroring the Python loader's tests (apps/agent/tests/
// test_mentor_variants.py). Catalog conformance against content/mentor_variants.json
// (exact count, every row parses, ability_id/mentor_id cross-refs) lives in
// mentor_variants-load.test.ts.

const ROW = {
  ability_id: "warrior_cleaving_blow",
  mentor_id: "guildmaster_torin",
  cost: { stamina: 3, focus: 0, scaling: null },
  effect: "Hits up to 2 adjacent enemies; +1 damage each.",
  narration_cue: "A wide Drathian arc — brutal and fast.",
  cultural_attribution: "Drathian Clans technique",
};

function variant(id: string, abilityId = "warrior_cleaving_blow"): MentorVariant {
  return parseMentorVariantRow(id, { ...ROW, ability_id: abilityId });
}

describe("parseMentorVariantRow — fail-loud validation", () => {
  test("accepts a valid row and round-trips fields", () => {
    const parsed = parseMentorVariantRow("warrior_cleaving_blow_drathian", ROW);
    expect(parsed.id).toBe("warrior_cleaving_blow_drathian");
    expect(parsed.ability_id).toBe("warrior_cleaving_blow");
    expect(parsed.mentor_id).toBe("guildmaster_torin");
    expect(parsed.cost).toEqual({ stamina: 3, focus: 0, scaling: null });
    expect(parsed.cultural_attribution).toBe("Drathian Clans technique");
  });

  test("rejects a non-object row", () => {
    expect(() => parseMentorVariantRow("x", null)).toThrow(/mentor_variants\[x\]/);
    expect(() => parseMentorVariantRow("x", [])).toThrow(/mentor_variants\[x\]/);
  });

  test("rejects a missing cultural_attribution", () => {
    const { cultural_attribution: _omit, ...rest } = ROW;
    expect(() => parseMentorVariantRow("x", rest)).toThrow(
      /mentor_variants\[x\]\.cultural_attribution/,
    );
  });

  test("rejects a missing ability_id", () => {
    const { ability_id: _omit, ...rest } = ROW;
    expect(() => parseMentorVariantRow("x", rest)).toThrow(/mentor_variants\[x\]\.ability_id/);
  });

  test("rejects a non-integer cost.stamina (parity with the Python int requirement)", () => {
    expect(() =>
      parseMentorVariantRow("x", { ...ROW, cost: { stamina: 2.5, focus: 0, scaling: null } }),
    ).toThrow(/mentor_variants\[x\]\.cost\.stamina/);
  });
});

describe("mentor_variants accessors", () => {
  afterAll(() => setMentorVariants(new Map()));

  test("getMentorVariant round-trips and is fail-loud on unknown", () => {
    setMentorVariants(
      new Map([["warrior_cleaving_blow_drathian", variant("warrior_cleaving_blow_drathian")]]),
    );
    expect(getMentorVariant("warrior_cleaving_blow_drathian").mentor_id).toBe("guildmaster_torin");
    expect(() => getMentorVariant("no_such_variant")).toThrow(/no_such_variant/);
  });

  test("getVariant resolves the (ability, variant) pair and fails loud on mismatch", () => {
    setMentorVariants(
      new Map([["warrior_cleaving_blow_drathian", variant("warrior_cleaving_blow_drathian")]]),
    );
    expect(
      getVariant("warrior_cleaving_blow", "warrior_cleaving_blow_drathian").cultural_attribution,
    ).toBe("Drathian Clans technique");
    expect(() => getVariant("guardian_taunt", "warrior_cleaving_blow_drathian")).toThrow(
      /warrior_cleaving_blow_drathian/,
    );
  });

  test("getVariantsForAbility groups by ability and returns [] for unknown", () => {
    setMentorVariants(
      new Map([
        ["warrior_cleaving_blow_drathian", variant("warrior_cleaving_blow_drathian")],
        ["warrior_cleaving_blow_keldaran", variant("warrior_cleaving_blow_keldaran")],
        ["guardian_taunt_thornwarden", variant("guardian_taunt_thornwarden", "guardian_taunt")],
      ]),
    );
    expect(
      getVariantsForAbility("warrior_cleaving_blow")
        .map((v) => v.id)
        .sort(),
    ).toEqual(["warrior_cleaving_blow_drathian", "warrior_cleaving_blow_keldaran"]);
    expect(getVariantsForAbility("unknown_ability")).toEqual([]);
  });
});
