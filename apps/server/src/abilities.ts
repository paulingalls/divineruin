import type { Ability, Cost, AbilityType } from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded archetype abilities (M2.2). Mirrors archetypes.ts: content/
// archetype_abilities.json -> archetype_abilities table, loaded at startup, parsed
// fail-loud, exposed via getAbility/getArchetypeAbilities. The Python agent reads the
// same table (apps/agent/abilities.py); the archetype_abilities.json row IS the
// cross-language contract and each loader owns fail-loud validation. This parser stays
// structurally symmetric with Python parse_ability_row. Cost is a {stamina, focus,
// scaling} object (decision m22-cost-object-schema) — there is NO cost_type enum;
// variable/pool costs (Lay on Hands, Divine Smite) carry their rule in scaling free-text.

const ABILITY_TYPES = new Set<AbilityType>(["core", "reaction", "elective"]);

// Runtime-loaded abilities, keyed by ability id (populated by loadAbilities at startup).
let abilities: ReadonlyMap<string, Ability> = new Map();

// get_ability is fail-loud (raises on unknown); get_archetype_abilities is a list query
// returning [] for unknown — constraint m22-ability-accessor-semantics, mirroring Python.
export function getAbility(id: string): Ability {
  const ability = abilities.get(id);
  if (!ability) throw new Error(`Unknown ability: ${id}`);
  return ability;
}

export function getArchetypeAbilities(archetypeId: string): Ability[] {
  return Array.from(abilities.values()).filter((a) => a.archetype_id === archetypeId);
}

export function setAbilities(map: ReadonlyMap<string, Ability>): void {
  abilities = map;
}

function parseCost(raw: unknown, ctx: string): Cost {
  const c = asRecord(raw, ctx);
  // Integer (not just number) for parity with the Python loader's _parse_cost, which
  // requires int — a shared row with a float cost must fail identically on both sides.
  // The typeof guard also narrows unknown -> number for the return.
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

export function parseAbilityRow(id: string, raw: unknown): Ability {
  const data = asRecord(raw, `abilities[${id}]`);
  const ctx = `abilities[${id}]`;

  if (
    typeof data.ability_type !== "string" ||
    !ABILITY_TYPES.has(data.ability_type as AbilityType)
  ) {
    throw new Error(`${ctx}.ability_type ${JSON.stringify(data.ability_type)} is invalid`);
  }
  if (typeof data.archetype_id !== "string") throw new Error(`${ctx}.archetype_id is not a string`);
  if (typeof data.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof data.level_requirement !== "number") {
    throw new Error(`${ctx}.level_requirement is not a number`);
  }
  if (typeof data.effect !== "string") throw new Error(`${ctx}.effect is not a string`);
  if (typeof data.narration_cue !== "string")
    throw new Error(`${ctx}.narration_cue is not a string`);

  return {
    id,
    archetype_id: data.archetype_id,
    name: data.name,
    ability_type: data.ability_type as AbilityType,
    level_requirement: data.level_requirement,
    cost: parseCost(data.cost, `${ctx}.cost`),
    effect: data.effect,
    narration_cue: data.narration_cue,
  };
}

export async function loadAbilities(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM archetype_abilities
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails
  // loud WITHOUT wiping an already-loaded map (mirrors the Python loader's discipline).
  const map = new Map<string, Ability>();
  for (const row of rows) {
    map.set(row.id, parseAbilityRow(row.id, row.data));
  }
  abilities = map;
  console.log(`Loaded ${map.size} archetype abilities`);
}
