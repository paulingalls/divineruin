import {
  validateActionExtensions,
  type ActionExtensions,
  type Recharge,
  type ChoirEffect,
} from "./action_contracts";

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
  "charm",
  "silence",
  "spell_redirect",
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
  "deafened",
  "shaken",
  "petrified",
  "cursed",
  "inspired",
  "hollowed",
  "temporary_hollowed",
  "iron_resolve",
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
  resolution?: "save" | "hit_then_save";
  save_success_damage?: "none" | "half";
  conditions_on_failure?: { applies_condition: string; duration: number }[];
  conditions_on_success?: { applies_condition: string; duration: number }[];
  reach?: number;
  type?: "melee" | "ranged" | "area";
  kind?: "attack";
  damage: string; // dice expression, e.g. "1d8", or "0" for a save-gated condition row
  damage_type: string; // "slashing" | "piercing" | ... | "none"
  ranged?: boolean;
  applies_condition?: string;
  save?: string;
  dc?: number;
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
  target_group: "allied_bandits";
  healing: string;
  recharge?: Recharge;
}

export interface EncounterPrepareAttackAction extends EncounterActionBase {
  kind: "prepare_attack";
  advantage: true;
  on_hit: { applies_condition: string; duration: number };
  recharge?: Recharge;
}

export type EncounterAction =
  | EncounterAttackAction
  | EncounterCommandAction
  | EncounterAccusationAction
  | EncounterHealingAction
  | EncounterPrepareAttackAction
  | (EncounterActionBase & ChoirEffect);

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
  difficulty: string; // "easy" | "moderate" | "hard"
  enemies: EncounterEnemy[];
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

export function validateEncounterReferences(
  encounter: unknown,
  creatureIds?: ReadonlySet<string>,
): void {
  if (!encounter || typeof encounter !== "object") throw new Error("encounter must be an object");
  const row = encounter as Record<string, unknown>;
  const label = `encounter '${String(row.id)}'`;
  const level = row.recommended_party_level;
  if (typeof level !== "number" || !Number.isInteger(level) || level < 1 || level > 20)
    throw new Error(`${label}: recommended_party_level must be an integer 1-20`);
  if (!Array.isArray(row.enemies) || !row.enemies.length)
    throw new Error(`${label}: enemies must be a nonempty list`);
  const seen = new Set<string>();
  for (const [index, value] of row.enemies.entries()) {
    if (!value || typeof value !== "object" || Array.isArray(value))
      throw new Error(`${label} enemy ${index}: expected reference object`);
    const enemy = value as Record<string, unknown>;
    const context = `${label} enemy '${typeof enemy.id === "string" ? enemy.id : index}'`;
    for (const field of ["id", "creature_id", "role"]) {
      if (typeof enemy[field] !== "string" || !enemy[field].trim())
        throw new Error(`${context}: ${field} must be a nonempty string`);
    }
    const extra = Object.keys(enemy).filter((key) => !["id", "creature_id", "role"].includes(key));
    if (extra.length) throw new Error(`${context}: forbidden reference fields ${extra.join(", ")}`);
    const id = enemy.id as string;
    if (seen.has(id)) throw new Error(`${context}: duplicate id`);
    seen.add(id);
    if (
      !["minion", "standard", "elite", "boss"].includes(enemy.role as string) &&
      !(enemy.role === "named" && enemy.creature_id === "hollow_choir")
    )
      throw new Error(`${context}: unsupported role '${String(enemy.role)}'`);
    if (creatureIds && !creatureIds.has(enemy.creature_id as string))
      throw new Error(`${context}: unknown creature_id '${String(enemy.creature_id)}'`);
  }
  if (
    row.enemies.some(
      (enemy: unknown) => (enemy as Record<string, unknown>).creature_id === "hollow_choir",
    ) &&
    row.enemies.length !== 1
  )
    throw new Error(`${label}: the Choir is solitary and must have one damage/reward owner`);
}

export interface SpatialPoint {
  x: number;
  y: number;
  z: number;
}
export type SpatialZone =
  | { center_id: string; radius_ft: number }
  | { kind: "silence"; center_id: string; radius_ft: number };

export interface ScenePlacement {
  party_start: SpatialPoint;
  companion_start: SpatialPoint;
  actors: Record<string, SpatialPoint>;
  locations: Record<string, SpatialPoint>;
  zones: Record<string, SpatialZone>;
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
function spatialPoint(value: unknown): void {
  const row = spatialMap(value);
  if (
    Object.keys(row).sort().join(",") !== "x,y,z" ||
    Object.values(row).some((v) => typeof v !== "number" || !Number.isFinite(v))
  )
    throw new Error("point requires finite x, y, z");
}
export function validateScenePlacement(encounter: unknown): void {
  const row = spatialMap(encounter);
  const scene = spatialMap(row.scene_placement);
  if (Object.keys(scene).sort().join(",") !== "actors,companion_start,locations,party_start,zones")
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
      (Object.hasOwn(zone, "kind") && zone.kind !== "silence") ||
      typeof zone.center_id !== "string" ||
      !(Object.hasOwn(actors, zone.center_id) || Object.hasOwn(locations, zone.center_id)) ||
      typeof zone.radius_ft !== "number" ||
      !Number.isFinite(zone.radius_ft) ||
      zone.radius_ft < 0
    )
      throw new Error("zone requires a known center and finite nonnegative radius");
  }
}
