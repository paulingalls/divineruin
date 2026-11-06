export interface God {
  god_id: string;
  layer_2_resonance: GodResonance;
  layer_3_tier_abilities: Record<GodTier, GodTierAbility>;
  layer_4_synergy_matrix: null;
  [legacyField: string]: unknown;
}
export type GodTier = "acknowledged" | "devoted" | "exalted";
export interface GodTierAbility {
  id: string;
  name: string;
  effect: string;
  recharge: "always" | "long_rest" | "per_session";
}
export interface GodResonance {
  name: string;
  effect: string;
  modifiers: GodModifier[];
}
export type GodModifier =
  | { kind: "flickering_damage_dice"; applies_to: "arcane_flickering"; value: number }
  | {
      kind: "generation_delta";
      applies_to: "combat_aid" | "natural_ground" | "hidden_or_stealthed" | "unvisited_location";
      value: number;
    }
  | { kind: "ward_penalty_immunity"; applies_to: "inside_active_veil_ward"; value: true }
  | { kind: "primal_multiplier_steps"; applies_to: "primal_on_natural_ground"; value: number }
  | { kind: "generation_override"; applies_to: "healing" | "target_at_zero_hp"; value: number }
  | { kind: "generation_multiplier"; applies_to: "wrongdoer_target"; value: number }
  | { kind: "echo_roll_choice"; applies_to: "overreach"; value: number };

const TIERS = ["acknowledged", "devoted", "exalted"];
const MODIFIERS: Record<string, { predicates: string[]; rule: string }> = {
  flickering_damage_dice: { predicates: ["arcane_flickering"], rule: "positive_integer" },
  generation_delta: {
    predicates: ["combat_aid", "natural_ground", "hidden_or_stealthed", "unvisited_location"],
    rule: "negative_integer",
  },
  ward_penalty_immunity: { predicates: ["inside_active_veil_ward"], rule: "true" },
  primal_multiplier_steps: { predicates: ["primal_on_natural_ground"], rule: "negative_integer" },
  generation_override: {
    predicates: ["healing", "target_at_zero_hp"],
    rule: "nonnegative_integer",
  },
  generation_multiplier: {
    predicates: ["wrongdoer_target"],
    rule: "positive_fraction_at_most_one",
  },
  echo_roll_choice: { predicates: ["overreach"], rule: "integer_at_least_two" },
};

function fail(path: string, reason: string): never {
  throw new Error(`${path}: ${reason}`);
}
function object(value: unknown, path: string, keys?: string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value))
    fail(path, "expected object");
  const row = value as Record<string, unknown>;
  if (keys) {
    for (const key of keys) if (!Object.hasOwn(row, key)) fail(`${path}.${key}`, "required field");
    for (const key of Object.keys(row))
      if (!keys.includes(key)) fail(`${path}.${key}`, "unknown field");
  }
  return row;
}
function text(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) fail(path, "expected nonblank string");
  return value;
}
function modifier(value: unknown, path: string): void {
  const row = object(value, path, ["kind", "applies_to", "value"]);
  const kind = text(row.kind, `${path}.kind`);
  if (!Object.hasOwn(MODIFIERS, kind)) fail(`${path}.kind`, "unknown modifier kind");
  const spec = MODIFIERS[kind]!;
  const predicate = text(row.applies_to, `${path}.applies_to`);
  if (!spec.predicates.includes(predicate)) fail(`${path}.applies_to`, `incompatible with ${kind}`);
  const number = row.value;
  let valid: boolean;
  if (spec.rule === "true") valid = number === true;
  else if (typeof number !== "number" || !Number.isFinite(number)) valid = false;
  else if (spec.rule === "positive_fraction_at_most_one") valid = number > 0 && number <= 1;
  else
    valid =
      Number.isInteger(number) &&
      ({
        positive_integer: number > 0,
        negative_integer: number < 0,
        nonnegative_integer: number >= 0,
        integer_at_least_two: number >= 2,
      }[spec.rule] ??
        false);
  if (!valid) fail(`${path}.value`, `expected ${spec.rule}`);
}

export function validateGod(profile: unknown): God {
  const identityPath = "god.god_id";
  const abilityIds = new Set<string>();
  const row = object(profile, identityPath);
  const patron = text(row.god_id, identityPath);
  let path = `${patron}.layer_2_resonance`;
  const resonance = object(row.layer_2_resonance, path, ["name", "effect", "modifiers"]);
  for (const field of ["name", "effect"]) text(resonance[field], `${path}.${field}`);
  if (!Array.isArray(resonance.modifiers) || !resonance.modifiers.length)
    fail(`${path}.modifiers`, "expected nonempty array");
  resonance.modifiers.forEach((entry: unknown, i: number) =>
    modifier(entry, `${path}.modifiers[${i}]`),
  );
  path = `${patron}.layer_3_tier_abilities`;
  const tiers = object(row.layer_3_tier_abilities, path, TIERS);
  for (const [tier, entry] of Object.entries(tiers)) {
    const abilityPath = `${path}.${tier}`;
    const ability = object(entry, abilityPath, ["id", "name", "effect", "recharge"]);
    for (const [field, value] of Object.entries(ability)) text(value, `${abilityPath}.${field}`);
    const id = text(ability.id, `${abilityPath}.id`);
    if (
      !id.startsWith(`${patron}_`) ||
      !/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(id.slice(patron.length + 1))
    )
      fail(`${abilityPath}.id`, "expected patron-prefixed snake_case");
    if (abilityIds.has(id)) fail(`${abilityPath}.id`, "duplicate ability id");
    abilityIds.add(id);
    if (
      !["always", "long_rest", "per_session"].includes(
        text(ability.recharge, `${abilityPath}.recharge`),
      )
    )
      fail(`${abilityPath}.recharge`, "unknown recharge");
  }
  if (!Object.hasOwn(row, "layer_4_synergy_matrix") || row.layer_4_synergy_matrix !== null)
    fail(`${patron}.layer_4_synergy_matrix`, "must be null");
  return row as God;
}

export function validateGods(profiles: unknown): God[] {
  if (!Array.isArray(profiles) || !profiles.length) fail("gods", "expected nonempty array");
  const patrons = new Set<string>();
  const abilityIds = new Set<string>();
  for (const [index, profile] of profiles.entries()) {
    const identityPath = `gods[${index}].god_id`;
    const row = object(profile, identityPath);
    const patron = text(row.god_id, identityPath);
    if (patrons.has(patron)) fail(`${patron}.god_id`, "duplicate patron");
    patrons.add(patron);
    const god = validateGod(profile);
    for (const [tier, ability] of Object.entries(god.layer_3_tier_abilities)) {
      if (abilityIds.has(ability.id))
        fail(`${patron}.layer_3_tier_abilities.${tier}.id`, "duplicate ability id");
      abilityIds.add(ability.id);
    }
  }
  return profiles as God[];
}
