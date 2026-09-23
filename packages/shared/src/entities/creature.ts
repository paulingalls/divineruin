import lootTables from "../../../../content/loot_tables.json";
import { REGION_IDS, type RegionId } from "./region";

// Encounter currency uses hollow_<class>; this base bestiary category is hollow. M7.2 (the regional
// catalog) turns encounter enemies into catalog references and applies that mapping.
export interface CreatureStatBlock {
  id: string;
  name: string;
  category: "hollow" | "beast" | "humanoid" | "construct" | "undead" | "elemental";
  tier: 1 | 2 | 3 | 4;
  home_region: RegionId | "multi_region";
  regions: RegionId[];
  description: string;
  level: number;
  hp: number;
  ac: number;
  speed: number;
  attributes: Record<"STR" | "DEX" | "CON" | "INT" | "WIS" | "CHA", number>;
  save_proficiencies: string[];
  attacks: Attack[];
  multiattack: string | null;
  passives: Ability[];
  actives: Ability[];
  reactions: Ability[];
  hollow: Hollow | null;
  behavior: { tactics: string; morale: string; group_size: string; environment: string[] };
  narration: {
    first_sighting: string;
    attack_cue: string;
    wounded_cue: string;
    death_cue: string;
    ambient_cue: string;
  };
  audio: {
    ambient: string;
    attack: string;
    hit: string;
    death: string;
    special: Record<string, string>;
  };
  loot_table_id: string;
  xp_reward: number;
}

export interface Attack {
  name: string;
  type: "melee" | "ranged" | "area";
  reach: number;
  to_hit: number;
  damage: string;
  damage_type: string;
  special: string | null;
  audio: string;
}

export interface Ability {
  name: string;
  description: string;
  narration_cue: string;
  recharge: string | null;
  audio: string | null;
}

export interface Hollow {
  class: "drift" | "rend" | "wrack" | "named";
  corruption_aura: number;
  resonance_on_death: number;
  veil_effect: string;
  vulnerable_to: string[];
}

const CATEGORIES = ["hollow", "beast", "humanoid", "construct", "undead", "elemental"];
const ATTACK_TYPES = ["melee", "ranged", "area"];
const HOLLOW_CLASSES = ["drift", "rend", "wrack", "named"];
const ATTRIBUTES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"];
const LOOT_IDS = new Set(lootTables.map((row) => row.id));
type Shape = Record<string, unknown>;
type Kind = "string" | "integer" | "object" | "array";
const isObject = (value: unknown): value is Shape =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function validateCreatureStatBlock(creature: unknown): string[] {
  const problems: string[] = [];
  if (!isObject(creature)) return ["creature: expected object"];

  function field(obj: Shape, key: string, path: string, kind: Kind, nullable = false): unknown {
    const name = path ? `${path}.${key}` : key;
    if (!(key in obj)) {
      problems.push(`${name}: required`);
      return undefined;
    }
    const value = obj[key];
    if (nullable && value === null) return value;
    const valid =
      kind === "string"
        ? typeof value === "string"
        : kind === "integer"
          ? Number.isInteger(value)
          : kind === "object"
            ? isObject(value)
            : Array.isArray(value);
    if (!valid) {
      problems.push(`${name}: expected ${kind}`);
      return undefined;
    }
    return value;
  }
  function strings(values: unknown[], path: string): void {
    values.forEach((value, i) => {
      if (typeof value !== "string") problems.push(`${path}[${i}]: expected string`);
    });
  }

  for (const key of ["id", "name"]) field(creature, key, "", "string");
  const category = field(creature, "category", "", "string");
  if (typeof category === "string" && !CATEGORIES.includes(category))
    problems.push(`category: expected ${CATEGORIES.join("|")}`);
  const tier = field(creature, "tier", "", "integer");
  if (typeof tier === "number" && ![1, 2, 3, 4].includes(tier))
    problems.push("tier: expected integer 1-4");
  const homeRegion = field(creature, "home_region", "", "string");
  if (
    typeof homeRegion === "string" &&
    homeRegion !== "multi_region" &&
    !(REGION_IDS as readonly string[]).includes(homeRegion)
  )
    problems.push("home_region: unknown region");
  const regions = field(creature, "regions", "", "array");
  if (Array.isArray(regions)) {
    if (regions.length === 0) problems.push("regions: expected non-empty array");
    regions.forEach((region, i) => {
      if (!(REGION_IDS as readonly unknown[]).includes(region))
        problems.push(`regions[${i}]: unknown region`);
    });
  }
  field(creature, "description", "", "string");
  for (const key of ["level", "hp", "ac", "speed"]) field(creature, key, "", "integer");
  const attributes = field(creature, "attributes", "", "object");
  if (isObject(attributes))
    for (const key of ATTRIBUTES) field(attributes, key, "attributes", "integer");
  const saves = field(creature, "save_proficiencies", "", "array");
  if (Array.isArray(saves)) strings(saves, "save_proficiencies");
  const attacks = field(creature, "attacks", "", "array");
  if (Array.isArray(attacks))
    attacks.forEach((attack, i) => {
      const path = `attacks[${i}]`;
      if (!isObject(attack)) {
        problems.push(`${path}: expected object`);
        return;
      }
      field(attack, "name", path, "string");
      const kind = field(attack, "type", path, "string");
      if (typeof kind === "string" && !ATTACK_TYPES.includes(kind))
        problems.push(`${path}.type: expected melee|ranged|area`);
      for (const key of ["reach", "to_hit"]) field(attack, key, path, "integer");
      for (const key of ["damage", "damage_type"]) field(attack, key, path, "string");
      field(attack, "special", path, "string", true);
      field(attack, "audio", path, "string");
    });
  field(creature, "multiattack", "", "string", true);
  for (const group of ["passives", "actives", "reactions"]) {
    const abilities = field(creature, group, "", "array");
    if (Array.isArray(abilities))
      abilities.forEach((ability, i) => {
        const path = `${group}[${i}]`;
        if (!isObject(ability)) {
          problems.push(`${path}: expected object`);
          return;
        }
        for (const key of ["name", "description", "narration_cue"])
          field(ability, key, path, "string");
        for (const key of ["recharge", "audio"]) field(ability, key, path, "string", true);
      });
  }
  if (!("hollow" in creature)) problems.push("hollow: required");
  else if (category === "hollow") {
    const hollow = creature.hollow;
    if (!isObject(hollow)) problems.push("hollow: expected object");
    else {
      const cls = field(hollow, "class", "hollow", "string");
      if (typeof cls === "string" && !HOLLOW_CLASSES.includes(cls))
        problems.push("hollow.class: expected drift|rend|wrack|named");
      for (const key of ["corruption_aura", "resonance_on_death"])
        field(hollow, key, "hollow", "integer");
      field(hollow, "veil_effect", "hollow", "string");
      const vulnerable = field(hollow, "vulnerable_to", "hollow", "array");
      if (Array.isArray(vulnerable)) strings(vulnerable, "hollow.vulnerable_to");
    }
  }
  const behavior = field(creature, "behavior", "", "object");
  if (isObject(behavior)) {
    for (const key of ["tactics", "morale", "group_size"])
      field(behavior, key, "behavior", "string");
    const environment = field(behavior, "environment", "behavior", "array");
    if (Array.isArray(environment)) strings(environment, "behavior.environment");
  }
  const narration = field(creature, "narration", "", "object");
  if (isObject(narration))
    for (const key of ["first_sighting", "attack_cue", "wounded_cue", "death_cue", "ambient_cue"])
      field(narration, key, "narration", "string");
  const audio = field(creature, "audio", "", "object");
  if (isObject(audio)) {
    for (const key of ["ambient", "attack", "hit", "death"]) field(audio, key, "audio", "string");
    const special = field(audio, "special", "audio", "object");
    if (isObject(special))
      for (const [key, value] of Object.entries(special))
        if (typeof value !== "string") problems.push(`audio.special.${key}: expected string`);
  }
  const lootId = field(creature, "loot_table_id", "", "string");
  if (typeof lootId === "string") {
    if (!LOOT_IDS.size) throw new Error("loot catalog is empty");
    if (!LOOT_IDS.has(lootId)) problems.push("loot_table_id: unknown loot table");
  }
  field(creature, "xp_reward", "", "integer");
  return problems;
}

// JSON.parse reads 8.0 as 8, while Python's json keeps it a float that fails "expected integer".
// The reviver's source text restores the difference; mapping any decimal or exponent literal to
// NaN leaves string and object checks unchanged and fails every integer check at its own path.
function decimalLiteralsAsNaN(
  _key: string,
  value: unknown,
  context?: { source?: string },
): unknown {
  if (typeof value !== "number") return value;
  if (context?.source === undefined) throw new Error("JSON.parse source text access is required");
  return /[.eE]/.test(context.source) ? Number.NaN : value;
}

export function parseCreatureJson(raw: string): unknown {
  return JSON.parse(raw, decimalLiteralsAsNaN);
}

export function validateCreatureJson(raw: string): string[] {
  const parsed = parseCreatureJson(raw);
  return Array.isArray(parsed)
    ? parsed.flatMap(validateCreatureStatBlock)
    : validateCreatureStatBlock(parsed);
}
