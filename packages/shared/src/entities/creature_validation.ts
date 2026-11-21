import { isObject, validateLegendary, type Shape } from "./legendary_contracts";
import { validateTurnTraits } from "./creature_turn_traits";
import { validateCreatureTraits } from "./creature_damage_affinity";
import { validateActionExtensions, validateRecharge } from "./action_contracts";
import { EXECUTABLE_ACTIVE_KINDS, STILL_FIELDS } from "./action_contracts_still";
import { TERRAIN_TYPE_VALUES } from "./terrain";
import lootTables from "../../../../content/loot_tables.json";
import { REGION_IDS } from "./region";
import {
  RESISTANCE_TAG_VALUES,
  validateEncounterActionKind,
  validateEncounterActionShape,
} from "./encounter";

const CATEGORIES = ["hollow", "beast", "humanoid", "construct", "undead", "elemental"];
const ATTACK_TYPES = ["melee", "ranged", "area"];
const HOLLOW_CLASSES = ["drift", "rend", "wrack", "named"];
const ATTRIBUTES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"];
const LOOT_IDS = new Set(lootTables.map((row) => row.id));
type Kind = "string" | "integer" | "boolean" | "object" | "array";
export function validateCreatureStatBlock(creature: unknown): string[] {
  const problems: string[] = [];
  if (!isObject(creature)) return ["creature: expected object"];

  function field(
    obj: Shape,
    key: string,
    path: string,
    kind: Kind,
    nullable = false,
    required = true,
  ): unknown {
    const name = path ? `${path}.${key}` : key;
    if (!(key in obj)) {
      if (required) problems.push(`${name}: required`);
      return undefined;
    }
    const value = obj[key];
    if (nullable && value === null) return value;
    const valid =
      kind === "string"
        ? typeof value === "string"
        : kind === "integer"
          ? Number.isInteger(value)
          : kind === "boolean"
            ? typeof value === "boolean"
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
  function combatEntry(action: Shape, path: string): void {
    try {
      if (
        typeof action.damage === "string" &&
        action.damage !== "0" &&
        !/^(?:[0-9]+|[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?)$/.test(String(action.damage))
      )
        throw new Error(`${path}.damage: invalid`);
      if (typeof action.recharge === "object" && action.recharge !== null)
        validateRecharge(action.recharge, `${path}.recharge`);
      validateEncounterActionShape(action, `enemy '${path}'`);
      validateEncounterActionKind(action, `enemy '${path}'`);
    } catch (error) {
      problems.push((error as Error).message);
    }
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
  const terrains = field(creature, "terrains", "", "array");
  if (Array.isArray(terrains)) {
    if (terrains.length === 0) problems.push("terrains: expected non-empty array");
    terrains.forEach((terrain, i) => {
      if (typeof terrain !== "string") problems.push(`terrains[${i}]: expected string`);
      else if (!(TERRAIN_TYPE_VALUES as readonly string[]).includes(terrain))
        problems.push(`terrains[${i}]: unknown terrain`);
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
      const before = problems.length;
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
      const properties = field(attack, "properties", path, "array", false, false);
      if (Array.isArray(properties)) strings(properties, `${path}.properties`);
      for (const [key, kind] of [
        ["applies_condition", "string"],
        ["save", "string"],
        ["dc", "integer"],
        ["half_on_success", "boolean"],
        ["escape_dc", "integer"],
      ] as const)
        field(attack, key, path, kind, false, false);
      if ("kind" in attack && attack.kind !== "attack")
        problems.push(`${path}.kind: expected attack`);
      if (problems.length === before) combatEntry(attack, path);
    });
  field(creature, "multiattack", "", "string", true);
  if ("multiattack_sequence" in creature) {
    const sequence = field(creature, "multiattack_sequence", "", "object");
    if (sequence && typeof sequence === "object" && !Array.isArray(sequence)) {
      const seq = sequence as Record<string, unknown>;
      const name = field(seq, "name", "multiattack_sequence", "string");
      const names = Array.isArray(attacks)
        ? attacks.flatMap((a: unknown) =>
            isObject(a) && typeof a.name === "string" ? [a.name.toLowerCase()] : [],
          )
        : [];
      const activeNames = Array.isArray(creature.actives)
        ? creature.actives.flatMap((a: unknown) =>
            isObject(a) && typeof a.name === "string" ? [a.name.toLowerCase()] : [],
          )
        : [];
      if (
        typeof name !== "string" ||
        !name.trim() ||
        [...names, ...activeNames].includes(name.toLowerCase())
      )
        problems.push("multiattack_sequence.name: empty or colliding action name");
      const references = (obj: Record<string, unknown>, key: string, path: string) => {
        const refs = field(obj, key, path, "array");
        if (Array.isArray(refs)) {
          if (!refs.length) problems.push(`${path}.${key}: expected non-empty array`);
          for (const ref of refs)
            if (
              typeof ref !== "string" ||
              names.filter((n) => n === ref.toLowerCase()).length !== 1
            )
              problems.push(`${path}.${key}: expected unambiguous attack reference`);
        }
      };
      references(seq, "attacks", "multiattack_sequence");
      if ("attacks_by_role" in seq) {
        const path = "multiattack_sequence.attacks_by_role";
        const overrides = field(seq, "attacks_by_role", "multiattack_sequence", "object");
        if (isObject(overrides))
          for (const role of Object.keys(overrides)) {
            if (role !== "elite" && role !== "boss") problems.push(`${path}.${role}: unknown role`);
            else references(overrides, role, path);
          }
      }
    }
  }
  for (const group of ["passives", "actives", "reactions"]) {
    const abilities = field(creature, group, "", "array");
    if (Array.isArray(abilities))
      abilities.forEach((ability, i) => {
        const path = `${group}[${i}]`;
        if (isObject(ability) && "turn_start_damage" in ability) {
          const effect = ability.turn_start_damage;
          if (
            group !== "passives" ||
            !isObject(effect) ||
            Object.keys(effect).length !== 3 ||
            effect.trigger !== "grappled_by_source" ||
            effect.damage !== "1d6" ||
            effect.damage_type !== "necrotic"
          )
            problems.push(`${path}.turn_start_damage: invalid automatic damage`);
        }
        const before = problems.length;
        if (!isObject(ability)) {
          problems.push(`${path}: expected object`);
          return;
        }
        for (const key of ["name", "description", "narration_cue"])
          field(ability, key, path, "string");
        field(ability, "audio", path, "string", true);
        if (
          (group !== "actives" && ability.kind !== "spell_redirect") ||
          (!(EXECUTABLE_ACTIVE_KINDS as readonly unknown[]).includes(ability.kind) &&
            !(
              ["command", "accusation"].includes(ability.kind as string) &&
              typeof ability.recharge === "object" &&
              ability.recharge !== null
            ))
        )
          field(ability, "recharge", path, "string", true);
        if (
          !("kind" in ability) &&
          [
            "resolution",
            "save_success_damage",
            "conditions_on_failure",
            "conditions_on_success",
            "duration_dice",
            "movement",
            "radius_ft",
            "rounds",
            "trigger",
            "redirect",
            ...STILL_FIELDS,
          ].some((key) => key in ability)
        )
          problems.push(`${path}.kind: required`);
        if (group === "reactions" && "kind" in ability) {
          try {
            if (ability.kind !== "spell_redirect") throw new Error(`${path}.kind: invalid`);
            validateActionExtensions(ability, path);
          } catch (error) {
            problems.push((error as Error).message);
          }
        }
        if (group === "actives") {
          const kind = field(ability, "kind", path, "string", false, false);
          const properties = field(ability, "properties", path, "array", false, false);
          if (Array.isArray(properties)) strings(properties, `${path}.properties`);
          if (kind !== undefined && problems.length === before) {
            if (
              kind === "attack" &&
              ability.damage === "0" &&
              ability.applies_condition &&
              !("duration" in ability) &&
              !(
                creature.id === "hollow_architect" &&
                ability.name === "Entomb" &&
                ability.applies_condition === "restrained"
              )
            )
              problems.push(`${path}.duration: invalid`);
            else combatEntry(ability, path);
          }
        }
      });
  }
  const signature = field(creature, "signature_ability", "", "object", false, false);
  if (isObject(signature)) {
    for (const key of ["name", "description"]) field(signature, key, "signature_ability", "string");
    if (typeof signature.narration_cue !== "string" || !signature.narration_cue.trim())
      problems.push("signature_ability.narration_cue: invalid");
  }
  const tags = field(creature, "resistance_tags", "", "array", false, false);
  if (Array.isArray(tags))
    for (const tag of tags)
      if (!(RESISTANCE_TAG_VALUES as readonly unknown[]).includes(tag))
        problems.push(
          `enemy 'resistance_tags' resistance_tags '${String(tag)}' not in ('${RESISTANCE_TAG_VALUES.join("', '")}')`,
        );
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
  return problems.concat(
    validateCreatureTraits(creature),
    validateTurnTraits(creature),
    validateLegendary(creature),
  );
}
