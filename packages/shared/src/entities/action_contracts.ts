import { CONDITION_NAMES } from "./encounter";

export type Recharge =
  { kind: "roll"; die: 6; threshold: number } | { kind: "encounter" | "round"; uses: number };
export type ActionExtensions = {
  recharge?: unknown;
  advantage?: unknown;
  duration?: unknown;
  damage?: unknown;
  damage_type?: unknown;
  kind?: unknown;
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
