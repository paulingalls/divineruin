import type { ActionExtensions, Recharge } from "./action_contracts";

export const STILL_ACTION_KINDS = ["rejection", "final_stillness", "illusion"] as const;
export const STILL_FIELDS = ["auto_hit", "minimum_destroyed_anchors", "check_skill"] as const;
export const EXECUTABLE_ACTIVE_KINDS = [
  "attack",
  "healing",
  "prepare_attack",
  "charm",
  "silence",
  ...STILL_ACTION_KINDS,
] as const;
type StillKind = (typeof STILL_ACTION_KINDS)[number];

export type StillEffect =
  | {
      kind: "rejection";
      save: "WIS";
      dc: number;
      radius_ft: number;
      recharge: Extract<Recharge, { kind: "roll" }>;
    }
  | {
      kind: "final_stillness";
      save: "WIS";
      dc: number;
      minimum_destroyed_anchors: number;
      duration_dice: string;
      recharge: { kind: "encounter"; uses: 1 };
    }
  | {
      kind: "illusion";
      check_skill: "investigation";
      dc: number;
      recharge: { kind: "round"; uses: 1 };
    };

export function validateStillAction(
  action: ActionExtensions,
  path: string,
  kind: unknown,
  invalid: (path: string) => never,
  positive: (value: unknown) => boolean,
  validateRecharge: (value: unknown, path: string) => void,
): boolean {
  if (
    "auto_hit" in action &&
    (action.auto_hit !== true ||
      kind !== "attack" ||
      action.type !== "melee" ||
      action.to_hit !== 0 ||
      typeof action.damage !== "string" ||
      !/^[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?$/.test(action.damage) ||
      typeof action.damage_type !== "string" ||
      !action.damage_type ||
      !positive(action.reach) ||
      action.applies_condition !== "charmed" ||
      action.save !== "WIS" ||
      !positive(action.dc) ||
      ["resolution", "half_on_success", "duration", "advantage"].some((key) => key in action))
  )
    invalid(`${path}.auto_hit`);
  if ("minimum_destroyed_anchors" in action && kind !== "final_stillness")
    invalid(`${path}.minimum_destroyed_anchors`);
  if ("check_skill" in action && kind !== "illusion") invalid(`${path}.check_skill`);
  if (!STILL_ACTION_KINDS.includes(kind as StillKind)) return false;
  const fields = {
    rejection: ["save", "radius_ft"],
    final_stillness: ["save", "minimum_destroyed_anchors", "duration_dice"],
    illusion: ["check_skill"],
  };
  const allowed = [
    "kind",
    "name",
    "description",
    "narration_cue",
    "audio",
    "properties",
    "recharge",
    "dc",
    ...fields[kind as StillKind],
  ];
  for (const key of Object.keys(action)) if (!allowed.includes(key)) invalid(`${path}.${key}`);
  if (!positive(action.dc)) invalid(`${path}.dc`);
  if (kind !== "illusion" && action.save !== "WIS") invalid(`${path}.save`);
  if (kind === "rejection" && !positive(action.radius_ft)) invalid(`${path}.radius_ft`);
  if (kind === "final_stillness") {
    if (!positive(action.minimum_destroyed_anchors) || Number(action.minimum_destroyed_anchors) > 6)
      invalid(`${path}.minimum_destroyed_anchors`);
    if (typeof action.duration_dice !== "string" || !/^1d[1-9][0-9]*$/.test(action.duration_dice))
      invalid(`${path}.duration_dice`);
  }
  if (kind === "illusion" && action.check_skill !== "investigation") invalid(`${path}.check_skill`);
  validateRecharge(action.recharge, `${path}.recharge`);
  const recharge = action.recharge as Recharge;
  const expected = { rejection: "roll", final_stillness: "encounter", illusion: "round" };
  if (recharge.kind !== expected[kind as StillKind] || ("uses" in recharge && recharge.uses !== 1))
    invalid(`${path}.recharge`);
  return true;
}
