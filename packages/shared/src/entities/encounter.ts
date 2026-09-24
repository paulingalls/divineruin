// Encounter templates carry combat and currency overlays around the bestiary
// CreatureStatBlock base in creature.ts. Their current enemy shape remains distinct.

import type { Attributes } from "./role_archetype";

// The 5 encounter roles. Value array is the single source of truth; the union is derived from it,
// so adding a role here updates both the type and the conformance test (which imports the array).
export const ENCOUNTER_ROLE_VALUES = ["minion", "standard", "elite", "boss", "named"] as const;
export type EncounterRole = (typeof ENCOUNTER_ROLE_VALUES)[number];

// The kinds an enemy action resolves as, mirrored from apps/agent/encounter_actions.py (constraint 7).
// An absent `kind` is "attack"; social mark actions never roll or carry strike fields.
export const ENCOUNTER_ACTION_KIND_VALUES = ["attack", "command", "accusation"] as const;
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

// One entry in an enemy's action_pool, as stored in encounter_templates.json. Matches the shape
// combat_init.py reads plus the content `description` blurb.
interface EncounterActionBase {
  name: string;
  properties: string[];
  description?: string;
}

// An attack deals `damage`; condition and half-damage fields select its post-hit or save-only shape.
export interface EncounterAttackAction extends EncounterActionBase {
  kind?: "attack";
  damage: string; // dice expression, e.g. "1d8", or "0" for a save-gated condition row
  damage_type: string; // "slashing" | "piercing" | ... | "none"
  ranged?: boolean;
  applies_condition?: string;
  save?: string;
  dc?: number;
  half_on_success?: boolean;
  escape_dc?: number;
}

export interface EncounterCommandAction extends EncounterActionBase {
  kind: "command";
}

export interface EncounterAccusationAction extends EncounterActionBase {
  kind: "accusation";
}

export type EncounterAction =
  EncounterAttackAction | EncounterCommandAction | EncounterAccusationAction;

export function encounterActionKind(action: {
  name?: unknown;
  kind?: unknown;
}): EncounterActionKind {
  const kind = action.kind === undefined ? "attack" : action.kind;
  if (!(ENCOUNTER_ACTION_KIND_VALUES as readonly unknown[]).includes(kind)) {
    throw new Error(
      `action ${pythonRepr(action.name)} has unknown kind ${pythonRepr(kind)}; expected one of ('attack', 'command', 'accusation')`,
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

export function validateEncounterActionShape(
  action: {
    name?: unknown;
    damage?: unknown;
    applies_condition?: unknown;
    save?: unknown;
    dc?: unknown;
    half_on_success?: unknown;
    properties?: unknown;
    escape_dc?: unknown;
    kind?: unknown;
    damage_type?: unknown;
  },
  context?: string,
): void {
  const label = context ?? `action ${String(action.name)}`;
  if (action.kind !== undefined) {
    const kind = encounterActionKind(action);
    if (kind !== "attack") {
      const carried = ["damage", "damage_type", "applies_condition"].filter((key) => key in action);
      if (carried.length)
        throw new Error(
          `${context ?? "enemy undefined"} ${kind} '${String(action.name)}' must not carry ['${carried.join("', '")}']: a mark action never rolls`,
        );
      return;
    }
  }
  if (
    Array.isArray(action.properties) &&
    action.properties.includes("grapple") &&
    !Number.isInteger(action.escape_dc)
  )
    throw new Error(
      `${label} grapple action needs an int 'escape_dc', got ${pythonRepr(action.escape_dc)}`,
    );
  const condition = action.applies_condition;
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
  name: string;
  level: number;
  tier: number;
  ac: number;
  hp: number;
  attributes: Attributes;
  action_pool: EncounterAction[];
  xp_value: number;
  sound_signature?: string;
  // Encounter-role overlay (M4.7). Optional: an untagged enemy derives as "standard" (identity).
  role?: EncounterRole;
  signature_ability?: SignatureAbility; // Boss only
  legendary_actions?: number; // Boss only (1/round)
}

export interface Encounter {
  id: string;
  name: string;
  description?: string;
  difficulty: string; // "easy" | "moderate" | "hard"
  enemies: EncounterEnemy[];
  stance_gate?: StanceGate;
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
