import type { Cost, MentorVariant } from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded mentor variant catalog (M9 / story-001). Mirrors spells.ts/abilities.ts:
// content/mentor_variants.json -> mentor_variants table, loaded at startup, parsed
// fail-loud, exposed via getMentorVariant/getVariant/getVariantsForAbility. The Python
// agent reads the same table (apps/agent/mentor_variants.py); the mentor_variants.json
// row IS the cross-language contract and each loader owns fail-loud validation. This
// parser stays structurally symmetric with Python parse_mentor_variant_row.
//
// A variant is FULLY specified (decision m9 override shape): its cost/effect/narration
// replace the base ability's wholesale on activation (story-003). cost reuses the shared
// Cost {stamina, focus, scaling} object from the abilities layer.

// Runtime-loaded variants, keyed by variant id (populated by loadMentorVariants at startup).
let mentorVariants: ReadonlyMap<string, MentorVariant> = new Map();

// getMentorVariant is fail-loud (raises on unknown); getVariantsForAbility is a list
// query returning [] for unknown — mirroring Python get_mentor_variant /
// get_variants_for_ability.
export function getMentorVariant(id: string): MentorVariant {
  const variant = mentorVariants.get(id);
  if (!variant) throw new Error(`Unknown mentor variant: ${id}`);
  return variant;
}

// The contracted accessor for the activation path (story-003): validates the variant
// exists AND belongs to the named base ability, so a stored active variant id that
// doesn't match the ability fails loud rather than overriding the wrong technique.
export function getVariant(abilityId: string, variantId: string): MentorVariant {
  const variant = getMentorVariant(variantId);
  if (variant.ability_id !== abilityId) {
    throw new Error(
      `Mentor variant ${variantId} belongs to ${variant.ability_id}, not ${abilityId}`,
    );
  }
  return variant;
}

export function getVariantsForAbility(abilityId: string): MentorVariant[] {
  return Array.from(mentorVariants.values()).filter((v) => v.ability_id === abilityId);
}

export function setMentorVariants(map: ReadonlyMap<string, MentorVariant>): void {
  mentorVariants = map;
}

function parseCost(raw: unknown, ctx: string): Cost {
  const c = asRecord(raw, ctx);
  // Integer (not just number) for parity with the Python loader's _parse_cost, which
  // requires int — a shared row with a float cost must fail identically on both sides.
  if (typeof c.stamina !== "number" || !Number.isInteger(c.stamina)) {
    throw new Error(`${ctx}.stamina is not an integer`);
  }
  if (typeof c.focus !== "number" || !Number.isInteger(c.focus)) {
    throw new Error(`${ctx}.focus is not an integer`);
  }
  if (c.scaling !== null && typeof c.scaling !== "string") {
    throw new Error(`${ctx}.scaling is not a string or null`);
  }
  return { stamina: c.stamina, focus: c.focus, scaling: c.scaling };
}

export function parseMentorVariantRow(id: string, raw: unknown): MentorVariant {
  const data = asRecord(raw, `mentor_variants[${id}]`);
  const ctx = `mentor_variants[${id}]`;

  if (typeof data.ability_id !== "string") throw new Error(`${ctx}.ability_id is not a string`);
  if (typeof data.mentor_id !== "string") throw new Error(`${ctx}.mentor_id is not a string`);
  if (typeof data.effect !== "string") throw new Error(`${ctx}.effect is not a string`);
  if (typeof data.narration_cue !== "string")
    throw new Error(`${ctx}.narration_cue is not a string`);
  if (typeof data.cultural_attribution !== "string") {
    throw new Error(`${ctx}.cultural_attribution is not a string`);
  }

  return {
    id,
    ability_id: data.ability_id,
    mentor_id: data.mentor_id,
    cost: parseCost(data.cost, `${ctx}.cost`),
    effect: data.effect,
    narration_cue: data.narration_cue,
    cultural_attribution: data.cultural_attribution,
  };
}

export async function loadMentorVariants(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM mentor_variants
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails
  // loud WITHOUT wiping an already-loaded map (mirrors the Python loader's discipline).
  const map = new Map<string, MentorVariant>();
  for (const row of rows) {
    map.set(row.id, parseMentorVariantRow(row.id, row.data));
  }
  mentorVariants = map;
  console.log(`Loaded ${map.size} mentor variants`);
}
