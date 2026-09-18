// Encounter template schema (Phase 4 M4.7 / story-001). content/encounter_templates.json is the
// single source of truth; apps/agent/combat_init.py loads a template and builds CombatParticipants
// from its enemies. This story adds the encounter-role overlay: each enemy carries a `role`
// (minion/standard/elite/boss/named) that encounter_roles.derive_role_stats scales at combat init,
// and Boss enemies author a `signature_ability` + `legendary_actions`.
//
// Only the `Attributes` shape is reused from the role_archetype/Npc schema. The action shape is
// local (`EncounterAction`): content actions carry a `description` blurb, distinct from CombatAction's
// `effect`. These types match the untyped enemy stat blocks combat_init.py consumes; a Phase-7
// Bestiary refactor will promote them to a shared CreatureStatBlock base.

import type { Attributes } from "./role_archetype";

// The 5 encounter roles. Value array is the single source of truth; the union is derived from it,
// so adding a role here updates both the type and the conformance test (which imports the array).
export const ENCOUNTER_ROLE_VALUES = ["minion", "standard", "elite", "boss", "named"] as const;
export type EncounterRole = (typeof ENCOUNTER_ROLE_VALUES)[number];

// The kinds an enemy action resolves as, mirrored from apps/agent/encounter_actions.py (constraint 7).
// An absent `kind` is "attack"; social mark actions never roll or carry strike fields.
export const ENCOUNTER_ACTION_KIND_VALUES = ["attack", "command", "accusation"] as const;
export type EncounterActionKind = (typeof ENCOUNTER_ACTION_KIND_VALUES)[number];

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
  | EncounterAttackAction
  | EncounterCommandAction
  | EncounterAccusationAction;

export function encounterActionKind(action: { name: string; kind?: string }): EncounterActionKind {
  const kind = action.kind ?? "attack";
  if (!(ENCOUNTER_ACTION_KIND_VALUES as readonly string[]).includes(kind)) {
    throw new Error(`action ${action.name} has unknown kind ${kind}`);
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

export function validateEncounterActionShape(action: {
  name?: unknown;
  damage?: unknown;
  applies_condition?: unknown;
  save?: unknown;
  dc?: unknown;
  half_on_success?: unknown;
}): void {
  const label = `action ${String(action.name)}`;
  const condition = action.applies_condition;
  const halfOnSuccess = action.half_on_success === true;
  if (condition !== undefined || halfOnSuccess) {
    const save = typeof action.save === "string" ? action.save.toLowerCase() : "";
    if (!SAVE_KEYS.has(save)) {
      throw new Error(`${label} condition/save damage needs a valid save`);
    }
    if (!Number.isInteger(action.dc)) {
      throw new Error(`${label} condition/save damage needs an integer dc`);
    }
  }
  if (
    halfOnSuccess &&
    (action.damage === undefined ||
      action.damage === "" ||
      action.damage === "0" ||
      action.damage === 0)
  ) {
    throw new Error(`${label} half_on_success needs damage`);
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
