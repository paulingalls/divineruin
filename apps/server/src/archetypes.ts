import type {
  Archetype,
  ArchetypeHp,
  ArchetypeResource,
  PoolFormula,
  StartingSkills,
  HpCategory,
  ResourcePattern,
} from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord, parseStringArray } from "./parse-helpers.ts";

// DB-loaded archetype chassis (M2.1). Mirrors items.ts/recipes.ts: content/
// archetypes.json -> archetypes table, loaded at startup, parsed fail-loud,
// exposed via getArchetypeChassis/listArchetypes. The Python agent reads the same
// table (apps/agent/archetypes.py); the archetypes.json row IS the cross-language
// chassis contract (constraint chassis-row-shape-contract) and each loader owns
// fail-loud validation. The TS type mirrors the nested JSON row shape; this parser
// stays structurally symmetric with Python parse_archetype_row (decision
// ef171c247d46) — armor/weapon closed-vocab lives in the content test, not here.

const HP_CATEGORIES = new Set<HpCategory>(["martial", "primal_divine", "arcane_shadow"]);
const RESOURCE_PATTERNS = new Set<ResourcePattern>([
  "stamina_only",
  "focus_only",
  "focus_primary",
  "split",
]);

// Runtime-loaded chassis (populated by loadArchetypes at startup).
let archetypes: ReadonlyMap<string, Archetype> = new Map();

export function getArchetypeChassis(id: string): Archetype | undefined {
  return archetypes.get(id);
}

export function listArchetypes(): Archetype[] {
  return Array.from(archetypes.values());
}

export function setArchetypes(map: ReadonlyMap<string, Archetype>): void {
  archetypes = map;
}

function parseFormula(raw: unknown, ctx: string): PoolFormula | null {
  if (raw === null) return null;
  const f = asRecord(raw, ctx);
  if (typeof f.base !== "number") throw new Error(`${ctx}.base is not a number`);
  if (typeof f.attribute !== "string") throw new Error(`${ctx}.attribute is not a string`);
  if (typeof f.level_divisor !== "number") throw new Error(`${ctx}.level_divisor is not a number`);
  return { base: f.base, attribute: f.attribute, level_divisor: f.level_divisor };
}

export function parseArchetypeRow(id: string, raw: unknown): Archetype {
  const data = asRecord(raw, `archetypes[${id}].data`);
  const ctx = `archetypes[${id}]`;

  const hpRaw = asRecord(data.hp, `${ctx}.hp`);
  if (typeof hpRaw.base !== "number") throw new Error(`${ctx}.hp.base is not a number`);
  if (typeof hpRaw.growth !== "number") throw new Error(`${ctx}.hp.growth is not a number`);
  if (typeof hpRaw.category !== "string" || !HP_CATEGORIES.has(hpRaw.category as HpCategory)) {
    throw new Error(`${ctx}.hp.category ${JSON.stringify(hpRaw.category)} is invalid`);
  }
  const hp: ArchetypeHp = {
    base: hpRaw.base,
    growth: hpRaw.growth,
    category: hpRaw.category as HpCategory,
  };

  const resRaw = asRecord(data.resource, `${ctx}.resource`);
  if (
    typeof resRaw.pattern !== "string" ||
    !RESOURCE_PATTERNS.has(resRaw.pattern as ResourcePattern)
  ) {
    throw new Error(`${ctx}.resource.pattern ${JSON.stringify(resRaw.pattern)} is invalid`);
  }
  const resource: ArchetypeResource = {
    pattern: resRaw.pattern as ResourcePattern,
    stamina_formula: parseFormula(resRaw.stamina_formula, `${ctx}.resource.stamina_formula`),
    focus_formula: parseFormula(resRaw.focus_formula, `${ctx}.resource.focus_formula`),
  };

  const skillsRaw = asRecord(data.starting_skills, `${ctx}.starting_skills`);
  if (typeof skillsRaw.num_choices !== "number") {
    throw new Error(`${ctx}.starting_skills.num_choices is not a number`);
  }
  const starting_skills: StartingSkills = {
    options: parseStringArray(skillsRaw.options, `${ctx}.starting_skills.options`),
    num_choices: skillsRaw.num_choices,
  };

  return {
    id,
    hp,
    resource,
    save_proficiencies: parseStringArray(data.save_proficiencies, `${ctx}.save_proficiencies`),
    armor_proficiencies: parseStringArray(data.armor_proficiencies, `${ctx}.armor_proficiencies`),
    weapon_proficiencies: parseStringArray(
      data.weapon_proficiencies,
      `${ctx}.weapon_proficiencies`,
    ),
    starting_skills,
  };
}

export async function loadArchetypes(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM archetypes
  `;
  const map = new Map<string, Archetype>();
  for (const row of rows) {
    map.set(row.id, parseArchetypeRow(row.id, row.data));
  }
  archetypes = map;
  console.log(`Loaded ${map.size} archetypes`);
}
