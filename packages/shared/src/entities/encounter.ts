import {
  validateActionExtensions,
  type ActionExtensions,
  type Recharge,
  type DurabilityRider,
  type ChoirEffect,
  type SummonConstructs,
} from "./action_contracts";

import { STILL_ACTION_KINDS, type StillEffect } from "./action_contracts_still";

// The 5 encounter roles. Value array is the single source of truth; the union is derived from it,
// so adding a role here updates both the type and the conformance test (which imports the array).
export const ENCOUNTER_ROLE_VALUES = ["minion", "standard", "elite", "boss", "named"] as const;
export type EncounterRole = (typeof ENCOUNTER_ROLE_VALUES)[number];

// The kinds an enemy action resolves as, mirrored from apps/agent/encounter_actions.py (constraint 7).
// An absent `kind` is "attack"; social mark actions never roll or carry strike fields.
export const ENCOUNTER_ACTION_KIND_VALUES = [
  "attack",
  "command",
  "accusation",
  "healing",
  "prepare_attack",
  "summon_constructs",
  "charm",
  "silence",
  "spell_redirect",
  ...STILL_ACTION_KINDS,
] as const;
export type EncounterActionKind = (typeof ENCOUNTER_ACTION_KIND_VALUES)[number];
const pythonRepr = (value: unknown): string => {
  if (value === undefined || value === null) return "None";
  if (typeof value === "string") return `'${value}'`;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
};
export const CONDITION_NAMES = [
  "wounded",
  "stunned",
  "prone",
  "grappled",
  "restrained",
  "incapacitated",
  "paralyzed",
  "poisoned",
  "blessed",
  "shielded",
  "enraged",
  "exhausted",
  "blinded",
  "frightened",
  "charmed",
  "taunted",
  "deafened",
  "shaken",
  "petrified",
  "cursed",
  "inspired",
  "regenerating",
  "precise_strike",
  "iron_stance",
  "reckless_assault",
  "crippled",
  "studied_weakness",
  "hollowed",
  "temporary_hollowed",
  "iron_resolve",
  "battle_cry",
  "war_cry_rally",
  "worthy_foe",
  "mark_of_justice",
  "incorporeal",
] as const;
export const RESISTANCE_TAG_VALUES = [
  "pragmatic",
  "emotional",
  "suspicious",
  "cowardly",
  "devout",
  "greedy",
  "honorable",
] as const;

// Runtime actions translated from the creature catalog.
interface EncounterActionBase {
  name: string;
  properties: string[];
  description?: string;
}

// An attack deals `damage`; condition and half-damage fields select its post-hit or save-only shape.
export interface EncounterAttackAction extends EncounterActionBase {
  magical?: boolean;
  auto_hit?: true;
  bonus_damage?: import("./action_contracts").DamageRider;
  critical_save?: import("./action_contracts").CriticalSave;
  durability_rider?: DurabilityRider;
  resolution?: "save" | "hit_then_save";
  save_success_damage?: "none" | "half";
  conditions_on_failure?: { applies_condition: string; duration: number | null; stage?: 1 }[];
  conditions_on_success?: { applies_condition: string; duration: number | null; stage?: 1 }[];
  reach?: number;
  type?: "melee" | "ranged" | "area";
  kind?: "attack";
  damage: string; // dice expression, e.g. "1d8", or "0" for a save-gated condition row
  damage_type: string; // "slashing" | "piercing" | ... | "none"
  ranged?: boolean;
  applies_condition?: string;
  save?: string;
  dc?: number;
  shape?: "cone";
  half_on_success?: boolean;
  escape_dc?: number;
  attack_source?: "catalog";
  self_heal?: "damage_dealt";
  to_hit?: number;
  advantage?: boolean;
  duration?: number;
  recharge?: Recharge;
}

export interface EncounterCommandAction extends EncounterActionBase {
  kind: "command";
}

export interface EncounterAccusationAction extends EncounterActionBase {
  kind: "accusation";
}

export interface EncounterHealingAction extends EncounterActionBase {
  kind: "healing";
  reach: number;
  target_group: "allied_bandits";
  healing: string;
  recharge?: Recharge;
}

export interface EncounterPrepareAttackAction extends EncounterActionBase {
  kind: "prepare_attack";
  advantage?: true;
  on_hit:
    { applies_condition: string; duration: number } | import("./action_contracts").PreparedDamage;
  recharge?: Recharge;
}

export type EncounterAction =
  | EncounterAttackAction
  | EncounterCommandAction
  | EncounterAccusationAction
  | EncounterHealingAction
  | EncounterPrepareAttackAction
  | (EncounterActionBase & (ChoirEffect | StillEffect | SummonConstructs));

export function encounterActionKind(action: {
  name?: unknown;
  kind?: unknown;
}): EncounterActionKind {
  const kind = action.kind === undefined ? "attack" : action.kind;
  if (!(ENCOUNTER_ACTION_KIND_VALUES as readonly unknown[]).includes(kind)) {
    throw new Error(
      `action ${pythonRepr(action.name)} has unknown kind ${pythonRepr(kind)}; expected one of ('${ENCOUNTER_ACTION_KIND_VALUES.join("', '")}')`,
    );
  }
  return kind as EncounterActionKind;
}

const SAVE_KEYS = new Set([
  "strength",
  "dexterity",
  "constitution",
  "intelligence",
  "wisdom",
  "charisma",
  "str",
  "dex",
  "con",
  "int",
  "wis",
  "cha",
]);

// Mirrors combat_init_validation.validate_enemy_action_shapes; `enemy` is its `enemy 'id'` prefix.
export function validateEncounterActionShape(
  action: ActionExtensions & {
    name?: unknown;
    damage?: unknown;
    applies_condition?: unknown;
    save?: unknown;
    dc?: unknown;
    half_on_success?: unknown;
    properties?: unknown;
    escape_dc?: unknown;
  },
  enemy?: string,
): void {
  const label =
    enemy === undefined
      ? `action ${String(action.name)}`
      : `${enemy} action ${pythonRepr(action.name)}`;
  validateActionExtensions(action, enemy?.replace(/^enemy '(.*)'$/, "$1") ?? "action");
  if (
    Array.isArray(action.properties) &&
    action.properties.includes("grapple") &&
    !Number.isInteger(action.escape_dc)
  )
    throw new Error(
      `${label} grapple action needs an int 'escape_dc', got ${pythonRepr(action.escape_dc)}`,
    );
  const condition = action.applies_condition ?? undefined;
  if (condition !== undefined && !(CONDITION_NAMES as readonly unknown[]).includes(condition))
    throw new Error(`${label} applies_condition ${pythonRepr(condition)} is not a known condition`);
  const halfOnSuccess = action.half_on_success === true;
  if (condition !== undefined || halfOnSuccess) {
    const save = typeof action.save === "string" ? action.save.toLowerCase() : "";
    if (!SAVE_KEYS.has(save)) {
      throw new Error(
        `${label} condition/save damage needs a valid 'save' attribute, got ${pythonRepr(action.save)}`,
      );
    }
    if (!Number.isInteger(action.dc)) {
      throw new Error(
        `${label} condition/save damage needs an int 'dc', got ${pythonRepr(action.dc)}`,
      );
    }
  }
  if (
    halfOnSuccess &&
    (action.damage === undefined ||
      action.damage === "" ||
      action.damage === "0" ||
      action.damage === 0)
  ) {
    throw new Error(`${label} half_on_success needs non-zero 'damage'`);
  }
}

const MARK_FORBIDDEN_FIELDS = ["damage", "damage_type", "applies_condition"] as const;

// Mirrors encounter_actions.validate_encounter_actions.
export function validateEncounterActionKind(
  action: ActionExtensions & { name?: unknown; kind?: unknown },
  enemy: string,
): void {
  const kind = encounterActionKind(action);
  validateActionExtensions(action, enemy.replace(/^enemy '(.*)'$/, "$1"));
  if (kind !== "command" && kind !== "accusation") return;
  const carried = MARK_FORBIDDEN_FIELDS.filter((key) => key in action);
  if (carried.length)
    throw new Error(
      `${enemy} ${kind} ${pythonRepr(action.name)} must not carry ['${carried.join("', '")}']: a mark action never rolls`,
    );
}

// A Boss's unique signature ability (authored content, not generated). derive_role_stats attaches
// it to the derived Boss; its in-combat firing is story-003.
export interface SignatureAbility {
  name: string;
  description: string;
  save?: string; // the attribute a target rolls to resist, when the signature forces a save
}

// A faction reputation gate (ashmark_patrol): combat is averted when the player is allied at or
// above the named tier.
export interface StanceGate {
  faction: string;
  allied_at_or_above: string;
}

export interface EncounterEnemy {
  id: string;
  creature_id: string;
  role: EncounterRole;
}

export interface Encounter {
  id: string;
  name: string;
  description?: string;
  recommended_party_level: number;
  recommended_party_size?: number;
  difficulty: string; // "easy" | "moderate" | "hard"
  enemies: EncounterEnemy[];
  witness?: string;
  accused?: string[];
  stance_gate?: StanceGate;
  scene_placement: ScenePlacement;
}

export function validateEncounterEnemyTier(
  encounterId: string,
  enemy: { id?: unknown; tier?: unknown },
): void {
  if (
    typeof enemy.tier !== "number" ||
    !Number.isInteger(enemy.tier) ||
    enemy.tier < 1 ||
    enemy.tier > 4
  ) {
    throw new Error(
      `encounter '${encounterId}' enemy '${String(enemy.id)}' has invalid tier ${String(enemy.tier)}`,
    );
  }
}

export { validateEncounterReferences } from "./encounter-references";

export interface SpatialPoint {
  x: number;
  y: number;
  z: number;
}
export type SpatialZone =
  | { center_id: string; radius_ft: number }
  | { kind: "silence" | "smoke"; center_id: string; radius_ft: number };
const AUTHORED_MOVEMENT_AREA_KINDS = ["water", "mud"] as const;
export type SpatialMovementArea = {
  kind: (typeof AUTHORED_MOVEMENT_AREA_KINDS)[number];
  excluded_actor_ids: string[];
} & (
  | { shape: "sphere"; center: SpatialPoint; radius_ft: number }
  | { shape: "rectangle"; min: SpatialPoint; max: SpatialPoint }
);

export interface ScenePlacement {
  party_start: SpatialPoint;
  companion_start: SpatialPoint;
  actors: Record<string, SpatialPoint>;
  locations: Record<string, SpatialPoint>;
  zones: Record<string, SpatialZone>;
  movement_areas?: Record<string, SpatialMovementArea>;
}

function spatialMap(value: unknown): Record<string, unknown> {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    Object.keys(value).some((key) => !key.trim())
  )
    throw new Error("spatial map requires nonempty IDs");
  return value as Record<string, unknown>;
}
function hasFields(row: Record<string, unknown>, fields: string[]): boolean {
  return (
    Object.keys(row).length === fields.length && fields.every((key) => Object.hasOwn(row, key))
  );
}

function spatialPoint(value: unknown): SpatialPoint {
  const row = spatialMap(value);
  if (!hasFields(row, ["x", "y", "z"]) || Object.values(row).some((v) => !Number.isFinite(v)))
    throw new Error("point requires finite x, y, z");
  return row as unknown as SpatialPoint;
}

function validateMovementAreas(value: unknown, actors: Record<string, unknown>): void {
  const common = ["shape", "kind", "excluded_actor_ids"];
  for (const [id, entry] of Object.entries(spatialMap(value))) {
    const area = spatialMap(entry);
    if (area.shape === "sphere" && hasFields(area, [...common, "center", "radius_ft"])) {
      spatialPoint(area.center);
      const radius = area.radius_ft as number;
      if (!Number.isFinite(radius) || radius <= 0)
        throw new Error("movement area radius must be positive and finite");
    } else if (area.shape === "rectangle" && hasFields(area, [...common, "min", "max"])) {
      const min = spatialPoint(area.min);
      const max = spatialPoint(area.max);
      if (min.x >= max.x || min.y >= max.y || min.z !== max.z)
        throw new Error("movement area rectangle requires positive extents at one height");
    } else {
      throw new Error("invalid movement area shape");
    }
    if (!AUTHORED_MOVEMENT_AREA_KINDS.some((kind) => kind === area.kind))
      throw new Error(`Authored movement area "${id}" requires water or mud`);
    const excluded = area.excluded_actor_ids;
    if (!Array.isArray(excluded) || new Set(excluded).size !== excluded.length)
      throw new Error("movement area exclusions must be a list of unique actor IDs");
    for (const id of excluded)
      if (typeof id !== "string" || !Object.hasOwn(actors, id))
        throw new Error("movement area exclusions must name authored enemies");
  }
}
export function validateScenePlacement(encounter: unknown): void {
  const row = spatialMap(encounter);
  const scene = spatialMap(row.scene_placement);
  const fields = ["actors", "companion_start", "locations", "party_start", "zones"];
  if (Object.hasOwn(scene, "movement_areas")) fields.push("movement_areas");
  if (!hasFields(scene, fields))
    throw new Error("scene_placement requires explicit starts, actors, locations and zones");
  spatialPoint(scene.party_start);
  spatialPoint(scene.companion_start);
  const actors = spatialMap(scene.actors),
    locations = spatialMap(scene.locations),
    zones = spatialMap(scene.zones);
  if (!Array.isArray(row.enemies)) throw new Error("missing enemies");
  const enemyIds = row.enemies.map((e) => spatialMap(e).id);
  if (
    new Set(enemyIds).size !== enemyIds.length ||
    Object.keys(actors).length !== enemyIds.length ||
    enemyIds.some((id) => typeof id !== "string" || !Object.hasOwn(actors, id))
  )
    throw new Error("scene must cover every enemy exactly");
  if (Object.hasOwn(scene, "movement_areas")) validateMovementAreas(scene.movement_areas, actors);
  for (const value of [...Object.values(actors), ...Object.values(locations)]) spatialPoint(value);
  const points = [
    scene.party_start,
    scene.companion_start,
    ...Object.values(actors),
    ...Object.values(locations),
  ] as SpatialPoint[];
  for (const a of points)
    for (const b of points)
      if (!Number.isFinite(Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)))
        throw new Error("nonfinite distance");
  const ids = [...Object.keys(actors), ...Object.keys(locations), ...Object.keys(zones)];
  if (new Set(ids).size !== ids.length) throw new Error("spatial IDs must be unique");
  for (const value of Object.values(zones)) {
    const zone = spatialMap(value);
    if (
      !["center_id,radius_ft", "center_id,kind,radius_ft"].includes(
        Object.keys(zone).sort().join(","),
      ) ||
      (Object.hasOwn(zone, "kind") && zone.kind !== "silence" && zone.kind !== "smoke") ||
      typeof zone.center_id !== "string" ||
      !(Object.hasOwn(actors, zone.center_id) || Object.hasOwn(locations, zone.center_id)) ||
      typeof zone.radius_ft !== "number" ||
      !Number.isFinite(zone.radius_ft) ||
      zone.radius_ft < 0
    )
      throw new Error("zone requires a known center and finite nonnegative radius");
  }
}
