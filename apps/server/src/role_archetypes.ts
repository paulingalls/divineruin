import type {
  ArchetypeService,
  Attributes,
  CombatAction,
  CombatStats,
  CombatVariant,
  RoleArchetype,
  ServiceCost,
} from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord, parseString, parseStringArray } from "./parse-helpers.ts";

// DB-loaded role archetype catalog (Phase 6 / M6.1, story-003). Mirrors mentor_variants.ts:
// content/role_archetypes.json -> role_archetypes table, loaded at startup, parsed fail-loud,
// exposed via getRoleArchetype. The Python agent reads the same table
// (apps/agent/role_archetypes.py); the role_archetypes.json row IS the cross-language
// contract and each loader owns fail-loud validation. parseRoleArchetypeRow stays
// structurally symmetric with the Python parse_role_archetype_row — same fields, same
// reject conditions. There is no instantiator on this side (create_npc_from_archetype is
// the Python rules engine); the server loads + validates so a malformed catalog crashes boot.
//
// String fields go through the shared parseString helper (parse-helpers.ts) rather than
// inline typeof checks. The role_type/disposition value arrays are inlined here, mirroring
// the Python loader's _ROLE_TYPES/_DISPOSITIONS (the shared const arrays are type-only across
// the package boundary).

const ROLE_TYPES = ["civilian", "military", "specialist"];
const DISPOSITIONS = ["hostile", "unfriendly", "neutral", "friendly", "trusted"];
let roleArchetypes: ReadonlyMap<string, RoleArchetype> = new Map();

export function getRoleArchetype(id: string): RoleArchetype {
  const archetype = roleArchetypes.get(id);
  if (!archetype) throw new Error(`Unknown role archetype: ${id}`);
  return archetype;
}

export function setRoleArchetypes(map: ReadonlyMap<string, RoleArchetype>): void {
  roleArchetypes = map;
}

// Integer (not just number) for parity with the Python loader's _parse_int. typeof excludes
// booleans (typeof true === "boolean"); Number.isInteger excludes floats — a shared row with
// a float where an int is required must fail identically on both sides.
function parseInt_(raw: unknown, ctx: string): number {
  if (typeof raw !== "number" || !Number.isInteger(raw)) throw new Error(`${ctx} is not an int`);
  return raw;
}

function parseNumber(raw: unknown, ctx: string): number {
  if (typeof raw !== "number" || !Number.isFinite(raw)) throw new Error(`${ctx} is not a number`);
  return raw;
}

function parseAttributes(raw: unknown, ctx: string): Attributes {
  const obj = asRecord(raw, ctx);
  return {
    strength: parseInt_(obj.strength, `${ctx}.strength`),
    dexterity: parseInt_(obj.dexterity, `${ctx}.dexterity`),
    constitution: parseInt_(obj.constitution, `${ctx}.constitution`),
    intelligence: parseInt_(obj.intelligence, `${ctx}.intelligence`),
    wisdom: parseInt_(obj.wisdom, `${ctx}.wisdom`),
    charisma: parseInt_(obj.charisma, `${ctx}.charisma`),
  };
}

function parseCombatAction(raw: unknown, ctx: string): CombatAction {
  const obj = asRecord(raw, ctx);
  return {
    name: parseString(obj.name, `${ctx}.name`),
    damage: parseString(obj.damage, `${ctx}.damage`),
    damage_type: parseString(obj.damage_type, `${ctx}.damage_type`),
    properties: parseStringArray(obj.properties, `${ctx}.properties`),
    ...(obj.effect === undefined || obj.effect === null
      ? {}
      : { effect: parseString(obj.effect, `${ctx}.effect`) }),
  };
}

function parseActionPool(raw: unknown, ctx: string): CombatAction[] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not an array`);
  return raw.map((a, i) => parseCombatAction(a, `${ctx}[${i}]`));
}

function parseCombatStats(raw: unknown, ctx: string): CombatStats | null {
  if (raw === null) return null;
  const obj = asRecord(raw, ctx);
  return {
    level: parseInt_(obj.level, `${ctx}.level`),
    hp: parseInt_(obj.hp, `${ctx}.hp`),
    ac: parseInt_(obj.ac, `${ctx}.ac`),
    attributes: parseAttributes(obj.attributes, `${ctx}.attributes`),
    action_pool: parseActionPool(obj.action_pool, `${ctx}.action_pool`),
    save_proficiencies: parseStringArray(obj.save_proficiencies ?? [], `${ctx}.save_proficiencies`),
    passives: parseStringArray(obj.passives ?? [], `${ctx}.passives`),
    actives: parseStringArray(obj.actives ?? [], `${ctx}.actives`),
  };
}

function parseCombatVariant(raw: unknown, ctx: string): CombatVariant {
  const obj = asRecord(raw, ctx);
  return {
    name: parseString(obj.name, `${ctx}.name`),
    level: parseInt_(obj.level, `${ctx}.level`),
    ...(obj.hp === undefined || obj.hp === null ? {} : { hp: parseInt_(obj.hp, `${ctx}.hp`) }),
    ...(obj.ac === undefined || obj.ac === null ? {} : { ac: parseInt_(obj.ac, `${ctx}.ac`) }),
    ...(obj.action_pool === undefined
      ? {}
      : { action_pool: parseActionPool(obj.action_pool, `${ctx}.action_pool`) }),
    passives: parseStringArray(obj.passives ?? [], `${ctx}.passives`),
    actives: parseStringArray(obj.actives ?? [], `${ctx}.actives`),
    ...(obj.notes === undefined || obj.notes === null
      ? {}
      : { notes: parseString(obj.notes, `${ctx}.notes`) }),
  };
}

function parseServiceCost(raw: unknown, ctx: string): ServiceCost {
  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    const obj = raw as Record<string, unknown>;
    return { min: parseNumber(obj.min, `${ctx}.min`), max: parseNumber(obj.max, `${ctx}.max`) };
  }
  return parseNumber(raw, ctx);
}

function parseArchetypeService(raw: unknown, ctx: string): ArchetypeService {
  const obj = asRecord(raw, ctx);
  const unit = parseString(obj.cost_unit, `${ctx}.cost_unit`);
  if (unit !== "sp" && unit !== "gp") throw new Error(`${ctx}.cost_unit is not "sp" or "gp"`);
  if (obj.requirements !== undefined && obj.requirements !== null) {
    asRecord(obj.requirements, `${ctx}.requirements`);
  }
  return {
    name: parseString(obj.name, `${ctx}.name`),
    cost: parseServiceCost(obj.cost, `${ctx}.cost`),
    cost_unit: unit,
    ...(obj.time_to_complete === undefined || obj.time_to_complete === null
      ? {}
      : { time_to_complete: parseString(obj.time_to_complete, `${ctx}.time_to_complete`) }),
    ...(obj.requirements === undefined || obj.requirements === null
      ? {}
      : { requirements: obj.requirements as Record<string, string> }),
    ...(obj.description === undefined || obj.description === null
      ? {}
      : { description: parseString(obj.description, `${ctx}.description`) }),
  };
}

export function parseRoleArchetypeRow(id: string, raw: unknown): RoleArchetype {
  const ctx = `role_archetypes[${id}]`;
  const data = asRecord(raw, ctx);

  const roleType = parseString(data.role_type, `${ctx}.role_type`);
  if (!ROLE_TYPES.includes(roleType)) throw new Error(`${ctx}.role_type ${roleType} is invalid`);
  const disposition = parseString(data.default_disposition, `${ctx}.default_disposition`);
  if (!DISPOSITIONS.includes(disposition)) {
    throw new Error(`${ctx}.default_disposition ${disposition} is invalid`);
  }
  if (data.inventory_pool !== null && typeof data.inventory_pool !== "string") {
    throw new Error(`${ctx}.inventory_pool is not a string or null`);
  }
  if (!Array.isArray(data.services)) throw new Error(`${ctx}.services is not an array`);
  if (data.combat_variants !== undefined && !Array.isArray(data.combat_variants)) {
    throw new Error(`${ctx}.combat_variants is not an array`);
  }
  const variants = (data.combat_variants ?? []) as unknown[];

  return {
    id,
    name: parseString(data.name, `${ctx}.name`),
    role_type: roleType as RoleArchetype["role_type"],
    default_disposition: disposition as RoleArchetype["default_disposition"],
    knowledge_domains: parseStringArray(data.knowledge_domains, `${ctx}.knowledge_domains`),
    services: data.services.map((s, i) => parseArchetypeService(s, `${ctx}.services[${i}]`)),
    inventory_pool: data.inventory_pool,
    price_modifier: parseNumber(data.price_modifier, `${ctx}.price_modifier`),
    combat_stats: parseCombatStats(data.combat_stats, `${ctx}.combat_stats`),
    combat_variants: variants.map((v, i) => parseCombatVariant(v, `${ctx}.combat_variants[${i}]`)),
  };
}

export async function loadRoleArchetypes(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM role_archetypes
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails loud
  // WITHOUT wiping an already-loaded map (mirrors the Python loader's discipline).
  const map = new Map<string, RoleArchetype>();
  for (const row of rows) {
    map.set(row.id, parseRoleArchetypeRow(row.id, row.data));
  }
  roleArchetypes = map;
  console.log(`Loaded ${map.size} role archetypes`);
}
