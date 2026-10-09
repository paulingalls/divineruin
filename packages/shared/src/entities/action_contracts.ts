import { CONDITION_NAMES } from "./encounter";

export type Recharge =
  { kind: "roll"; die: 6; threshold: number } | { kind: "encounter" | "round"; uses: number };
export type DurabilityRider = {
  save: "STR" | "DEX" | "CON" | "INT" | "WIS" | "CHA";
  dc: number;
  dice: string;
  target: "selected_player_held_item";
};
export type ActionExtensions = {
  durability_rider?: unknown;
  duration_dice?: unknown;
  movement?: unknown;
  radius_ft?: unknown;
  rounds?: unknown;
  trigger?: unknown;
  redirect?: unknown;
  resolution?: unknown;
  save_success_damage?: unknown;
  conditions_on_failure?: unknown;
  conditions_on_success?: unknown;
  reach?: unknown;
  type?: unknown;
  attack_source?: unknown;
  to_hit?: unknown;
  self_heal?: unknown;
  recharge?: unknown;
  advantage?: unknown;
  duration?: unknown;
  damage?: unknown;
  damage_type?: unknown;
  kind?: unknown;
  applies_condition?: unknown;
  save?: unknown;
  dc?: unknown;
  half_on_success?: unknown;
  escape_dc?: unknown;
  target_group?: unknown;
  healing?: unknown;
  on_hit?: unknown;
};
function invalid(path: string): never {
  throw new Error(`${path}: invalid`);
}
const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const positive = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value > 0;

export function validateRecharge(value: unknown, path: string): void {
  if (!object(value)) invalid(path);
  const kind = value.kind;
  if (!["roll", "encounter", "round"].includes(kind as string)) invalid(`${path}.kind`);
  const fields = kind === "roll" ? ["kind", "die", "threshold"] : ["kind", "uses"];
  for (const key of Object.keys(value)) if (!fields.includes(key)) invalid(`${path}.${key}`);
  if (kind === "roll") {
    if (value.die !== 6) invalid(`${path}.die`);
    if (!positive(value.threshold) || value.threshold > 6) invalid(`${path}.threshold`);
  } else if (!positive(value.uses)) invalid(`${path}.uses`);
}

export function validateActionExtensions(action: ActionExtensions, path: string): void {
  const kind = action.kind === undefined ? "attack" : action.kind;
  validateDurabilityRider(action, path);
  validateResolution(action, path);
  if (
    !["charm", "silence", "spell_redirect"].includes(kind as string) &&
    ["duration_dice", "movement", "radius_ft", "rounds", "trigger", "redirect"].some(
      (key) => key in action,
    )
  )
    invalid(`${path}.kind`);
  if (["charm", "silence", "spell_redirect"].includes(kind as string)) {
    validateChoirEffect(action, path);
    return;
  }
  if ("attack_source" in action) {
    if (kind !== "attack" || action.attack_source !== "catalog") invalid(`${path}.attack_source`);
    const saveOnly =
      action.resolution === "save" ||
      action.half_on_success === true ||
      action.damage === "0" ||
      action.damage === 0;
    if (!saveOnly && !Number.isInteger(action.to_hit)) invalid(`${path}.to_hit`);
  }
  if (
    "self_heal" in action &&
    (kind !== "attack" ||
      action.self_heal !== "damage_dealt" ||
      action.damage == null ||
      action.damage === "" ||
      action.damage === "0" ||
      action.damage === 0)
  )
    invalid(`${path}.self_heal`);
  if (["attack", "healing", "prepare_attack"].includes(kind as string) && "recharge" in action)
    validateRecharge(action.recharge, `${path}.recharge`);
  if ("advantage" in action && typeof action.advantage !== "boolean") invalid(`${path}.advantage`);
  if ("duration" in action && !positive(action.duration)) invalid(`${path}.duration`);
  let forbidden: string[];
  if (kind === "attack") {
    if (action.kind === "attack") {
      for (const key of ["damage", "damage_type"] as const)
        if (typeof action[key] !== "string") invalid(`${path}.${key}`);
    }
    if (action.kind === "attack") {
      for (const key of [
        "applies_condition",
        "save",
        "dc",
        "half_on_success",
        "escape_dc",
      ] as const) {
        if (!(key in action)) continue;
        const valid =
          key === "half_on_success"
            ? typeof action[key] === "boolean"
            : key === "dc" || key === "escape_dc"
              ? Number.isInteger(action[key])
              : typeof action[key] === "string";
        if (!valid) invalid(`${path}.${key}`);
      }
    }
    if (action.kind === "attack" && action.damage === "0") {
      const condition = (action as Record<string, unknown>).applies_condition;
      if (typeof condition !== "string" || !condition) invalid(`${path}.applies_condition`);
      if (action.damage_type !== "none") invalid(`${path}.damage_type`);
    }
    forbidden = ["target_group", "healing", "on_hit"];
  } else if (kind === "healing" || kind === "prepare_attack") {
    forbidden = [
      "damage",
      "damage_type",
      "applies_condition",
      "save",
      "dc",
      "half_on_success",
      "escape_dc",
    ];
    if (kind === "healing") {
      forbidden.push("advantage", "on_hit");
      if (action.target_group !== "allied_bandits") invalid(`${path}.target_group`);
      if (
        typeof action.healing !== "string" ||
        !/^[1-9][0-9]*d[1-9][0-9]*(?:\+[0-9]+)?$/.test(action.healing)
      )
        invalid(`${path}.healing`);
    } else {
      forbidden.push("target_group", "healing");
      if (action.advantage !== true) invalid(`${path}.advantage`);
      const rider = action.on_hit;
      if (!object(rider)) invalid(`${path}.on_hit`);
      if (!(CONDITION_NAMES as readonly unknown[]).includes(rider.applies_condition))
        invalid(`${path}.on_hit.applies_condition`);
      if (!positive(rider.duration)) invalid(`${path}.on_hit.duration`);
      for (const key of Object.keys(rider))
        if (!["applies_condition", "duration"].includes(key)) invalid(`${path}.on_hit.${key}`);
    }
  } else forbidden = ["target_group", "healing", "advantage", "on_hit"];
  for (const key of forbidden) if (key in action) invalid(`${path}.${key}`);
}

function validateResolution(action: ActionExtensions, path: string): void {
  const structured = [
    "resolution",
    "save_success_damage",
    "conditions_on_failure",
    "conditions_on_success",
  ];
  if (!structured.some((key) => key in action)) return;
  const mode = action.resolution;
  if ((action.kind ?? "attack") !== "attack" || !["save", "hit_then_save"].includes(mode as string))
    invalid(`${path}.resolution`);
  if (
    ["applies_condition", "duration", "half_on_success", "escape_dc"].some((key) => key in action)
  )
    invalid(`${path}.resolution`);
  if (
    typeof action.save !== "string" ||
    ![
      "str",
      "dex",
      "con",
      "int",
      "wis",
      "cha",
      "strength",
      "dexterity",
      "constitution",
      "intelligence",
      "wisdom",
      "charisma",
    ].includes(action.save.toLowerCase())
  )
    invalid(`${path}.save`);
  if (!positive(action.dc)) invalid(`${path}.dc`);
  if (
    typeof action.damage !== "string" ||
    !/^[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?$/.test(action.damage)
  )
    invalid(`${path}.damage`);
  if (typeof action.damage_type !== "string" || !action.damage_type) invalid(`${path}.damage_type`);
  if (!positive(action.reach) || !["area", "ranged", "melee"].includes(action.type as string))
    invalid(`${path}.reach`);
  if (mode === "save") {
    if (!["none", "half"].includes(action.save_success_damage as string))
      invalid(`${path}.save_success_damage`);
    if ("to_hit" in action && action.to_hit !== 0) invalid(`${path}.to_hit`);
  } else if ("save_success_damage" in action || !Number.isInteger(action.to_hit))
    invalid(`${path}.to_hit`);
  for (const key of ["conditions_on_failure", "conditions_on_success"] as const) {
    const riders = action[key];
    if (!Array.isArray(riders)) invalid(`${path}.${key}`);
    const seen = new Set();
    for (const rider of riders) {
      if (!object(rider) || Object.keys(rider).sort().join(",") !== "applies_condition,duration")
        invalid(`${path}.${key}`);
      if (
        !(CONDITION_NAMES as readonly unknown[]).includes(rider.applies_condition) ||
        seen.has(rider.applies_condition)
      )
        invalid(`${path}.${key}.applies_condition`);
      seen.add(rider.applies_condition);
      if (!positive(rider.duration)) invalid(`${path}.${key}.duration`);
    }
  }
}

export type ChoirEffect =
  | {
      kind: "charm";
      save: string;
      dc: number;
      duration_dice: "1d4";
      movement: "approach_source";
      recharge?: Recharge;
    }
  | { kind: "silence"; radius_ft: number; rounds: number; recharge?: Recharge }
  | {
      kind: "spell_redirect";
      save: string;
      dc: number;
      trigger: "verbal_spell";
      redirect: "caster";
    };

function validateChoirEffect(action: ActionExtensions, path: string): void {
  const kind = action.kind as "charm" | "silence" | "spell_redirect";
  const allowed = kind === "silence" ? [] : ["save", "dc"];
  for (const key of [
    "damage",
    "damage_type",
    "applies_condition",
    "save",
    "dc",
    "half_on_success",
    "escape_dc",
    "target_group",
    "healing",
    "advantage",
    "on_hit",
    "resolution",
    "save_success_damage",
    "conditions_on_failure",
    "conditions_on_success",
    "duration",
    "to_hit",
  ])
    if (key in action && !allowed.includes(key)) invalid(`${path}.${key}`);
  const fields = {
    charm: ["duration_dice", "movement"],
    silence: ["radius_ft", "rounds"],
    spell_redirect: ["trigger", "redirect"],
  }[kind];
  for (const key of ["duration_dice", "movement", "radius_ft", "rounds", "trigger", "redirect"])
    if (key in action && !fields.includes(key)) invalid(`${path}.${key}`);
  if (kind !== "silence") {
    if (typeof action.save !== "string" || !["wis", "wisdom"].includes(action.save.toLowerCase()))
      invalid(`${path}.save`);
    if (!positive(action.dc)) invalid(`${path}.dc`);
  }
  if (kind === "charm") {
    if (action.duration_dice !== "1d4" || action.movement !== "approach_source")
      invalid(`${path}.duration_dice`);
  } else if (kind === "silence") {
    if (!positive(action.radius_ft) || !positive(action.rounds)) invalid(`${path}.radius_ft`);
  } else if (action.trigger !== "verbal_spell" || action.redirect !== "caster")
    invalid(`${path}.trigger`);
  if (kind === "spell_redirect" && "recharge" in action && action.recharge !== null)
    invalid(`${path}.recharge`);
  if ("recharge" in action && !(kind === "spell_redirect" && action.recharge === null))
    validateRecharge(action.recharge, `${path}.recharge`);
}

function validateDurabilityRider(action: ActionExtensions, path: string): void {
  if (!("durability_rider" in action)) return;
  const rider = action.durability_rider;
  path += ".durability_rider";
  if (
    (action.kind ?? "attack") !== "attack" ||
    action.resolution === "save" ||
    action.half_on_success
  )
    invalid(path);
  if (!object(rider) || Object.keys(rider).sort().join(",") !== "dc,dice,save,target")
    invalid(path);
  if (!["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(rider.save as string))
    invalid(`${path}.save`);
  if (!positive(rider.dc)) invalid(`${path}.dc`);
  if (typeof rider.dice !== "string" || !/^[1-9][0-9]*d[1-9][0-9]*$/.test(rider.dice))
    invalid(`${path}.dice`);
  if (rider.target !== "selected_player_held_item") invalid(`${path}.target`);
}
