import type { Item, ItemEffect, ItemAttunement } from "@divineruin/shared";
import { sql } from "./db.ts";

// DB-loaded item content (M5.4). Mirrors recipes.ts: content/items.json -> items
// table, loaded at startup, parsed fail-loud, exposed via getItem/listItems. The
// Python agent reads items raw from the same table (db_content_queries.get_item);
// shape validation is owned here at the TS load boundary (constraint 8508fdb1abc3).
// Replaces the former inline validator in items-load.test.ts (debt aa78e26e81a8).

const ALLOWED_TIERS = new Set<Item["tier"]>([1, 2, 3, 4]);
const ALLOWED_RARITIES = new Set(["common", "uncommon", "rare", "legendary"]);
const ALLOWED_DURABILITY_TIERS = new Set<NonNullable<Item["durability_tier"]>>([
  "fragile",
  "standard",
  "reinforced",
  "masterwork",
]);
const ATTUNEMENT_KINDS = new Set(["none", "required", "class"]);

// Runtime-loaded items (populated by loadItems at startup).
let items: ReadonlyMap<string, Item> = new Map();

export function getItem(id: string): Item | undefined {
  return items.get(id);
}

export function listItems(): Item[] {
  return Array.from(items.values());
}

export function setItems(map: ReadonlyMap<string, Item>): void {
  items = map;
}

function asRecord(raw: unknown, ctx: string): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`${ctx} is not an object`);
  }
  return raw as Record<string, unknown>;
}

function parseItemEffect(raw: unknown, ctx: string): ItemEffect {
  const e = asRecord(raw, ctx);
  if (typeof e.type !== "string") throw new Error(`${ctx}.type is not a string`);
  if (e.target !== undefined && typeof e.target !== "string") {
    throw new Error(`${ctx}.target is not a string`);
  }
  if (e.value !== undefined && typeof e.value !== "number" && typeof e.value !== "string") {
    throw new Error(`${ctx}.value is not number or string`);
  }
  if (e.trigger !== undefined && typeof e.trigger !== "string") {
    throw new Error(`${ctx}.trigger is not a string`);
  }
  if (e.description !== undefined && typeof e.description !== "string") {
    throw new Error(`${ctx}.description is not a string`);
  }
  return e as unknown as ItemEffect;
}

function parseAttunement(raw: unknown, ctx: string): ItemAttunement {
  const a = asRecord(raw, ctx);
  if (typeof a.kind !== "string" || !ATTUNEMENT_KINDS.has(a.kind)) {
    throw new Error(`${ctx}.kind ${String(a.kind)} is not none|required|class`);
  }
  if (a.kind === "class") {
    if (typeof a.class !== "string" || a.class.length === 0) {
      throw new Error(`${ctx}.class is required (non-empty string) when kind is class`);
    }
    return { kind: "class", class: a.class };
  }
  return { kind: a.kind as "none" | "required" };
}

function parseStringArray(raw: unknown, ctx: string): string[] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not an array`);
  return raw.map((v, i) => {
    if (typeof v !== "string") throw new Error(`${ctx}[${i}] is not a string`);
    return v;
  });
}

/**
 * Canonical fail-loud parser for one items-table row. Validates the required Item
 * fields and the optional crafting-system fields' SHAPE when present (tier/rarity/
 * durability_tier enums, the attunement union, effects[], art_template.vars).
 * Throws with an `items[<id>].<field>` context on any mismatch. Validates a single
 * item in isolation — magic-item->recipe-tier referential checks are a cross-entity
 * concern owned by the content-validation test. Per-type structured-field
 * REQUIREMENTS (weapon->damage_dice, armor->ac, equippable->durability_tier) tighten
 * in story-002 Commit 4 alongside the content that satisfies them.
 */
export function parseItemRow(id: string, raw: unknown): Item {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`items[${id}].data is not an object`);
  }
  const data = raw as Record<string, unknown>;
  const ctx = `items[${id}]`;

  if (typeof data.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof data.tier !== "number" || !ALLOWED_TIERS.has(data.tier as Item["tier"])) {
    throw new Error(`${ctx}.tier ${String(data.tier)} is not 1|2|3|4`);
  }
  if (typeof data.type !== "string") throw new Error(`${ctx}.type is not a string`);
  if (typeof data.rarity !== "string" || !ALLOWED_RARITIES.has(data.rarity)) {
    throw new Error(`${ctx}.rarity ${String(data.rarity)} is not common|uncommon|rare|legendary`);
  }
  const tags = parseStringArray(data.tags, `${ctx}.tags`);
  if (typeof data.weight !== "number") throw new Error(`${ctx}.weight is not a number`);
  if (!Array.isArray(data.effects)) throw new Error(`${ctx}.effects is not an array`);
  const effects = data.effects.map((e, i) => parseItemEffect(e, `${ctx}.effects[${i}]`));
  if (typeof data.value_base !== "number") throw new Error(`${ctx}.value_base is not a number`);

  const item: Item = {
    id,
    name: data.name,
    tier: data.tier as Item["tier"],
    type: data.type,
    rarity: data.rarity,
    tags,
    weight: data.weight,
    effects,
    value_base: data.value_base,
  };

  if (data.subtype !== undefined) {
    if (typeof data.subtype !== "string") throw new Error(`${ctx}.subtype is not a string`);
    item.subtype = data.subtype;
  }
  if (data.description !== undefined) {
    if (typeof data.description !== "string") throw new Error(`${ctx}.description is not a string`);
    item.description = data.description;
  }
  if (data.lore !== undefined) {
    if (typeof data.lore !== "string") throw new Error(`${ctx}.lore is not a string`);
    item.lore = data.lore;
  }
  if (data.found_in !== undefined)
    item.found_in = parseStringArray(data.found_in, `${ctx}.found_in`);
  if (data.value_modifiers !== undefined) {
    const vm = asRecord(data.value_modifiers, `${ctx}.value_modifiers`);
    for (const [k, v] of Object.entries(vm)) {
      if (typeof v !== "number") throw new Error(`${ctx}.value_modifiers[${k}] is not a number`);
    }
    item.value_modifiers = vm as Record<string, number>;
  }
  if (data.durability_tier !== undefined) {
    if (
      typeof data.durability_tier !== "string" ||
      !ALLOWED_DURABILITY_TIERS.has(data.durability_tier as NonNullable<Item["durability_tier"]>)
    ) {
      throw new Error(`${ctx}.durability_tier ${JSON.stringify(data.durability_tier)} is invalid`);
    }
    item.durability_tier = data.durability_tier as Item["durability_tier"];
  }
  if (data.current_hits !== undefined) {
    if (typeof data.current_hits !== "number")
      throw new Error(`${ctx}.current_hits is not a number`);
    item.current_hits = data.current_hits;
  }
  if (data.damage_dice !== undefined) {
    if (typeof data.damage_dice !== "string") throw new Error(`${ctx}.damage_dice is not a string`);
    item.damage_dice = data.damage_dice;
  }
  if (data.properties !== undefined) {
    item.properties = parseStringArray(data.properties, `${ctx}.properties`);
  }
  if (data.ac !== undefined) {
    if (typeof data.ac !== "number") throw new Error(`${ctx}.ac is not a number`);
    item.ac = data.ac;
  }
  if (data.armor_properties !== undefined) {
    item.armor_properties = parseStringArray(data.armor_properties, `${ctx}.armor_properties`);
  }
  if (data.audio_cue !== undefined) {
    if (typeof data.audio_cue !== "string") throw new Error(`${ctx}.audio_cue is not a string`);
    item.audio_cue = data.audio_cue;
  }
  if (data.attunement !== undefined) {
    item.attunement = parseAttunement(data.attunement, `${ctx}.attunement`);
  }
  if (data.quest_only !== undefined) {
    if (typeof data.quest_only !== "boolean") throw new Error(`${ctx}.quest_only is not a boolean`);
    item.quest_only = data.quest_only;
  }
  if (data.art_template !== undefined) {
    const at = asRecord(data.art_template, `${ctx}.art_template`);
    if (typeof at.template_id !== "string") {
      throw new Error(`${ctx}.art_template.template_id is not a string`);
    }
    const vars = asRecord(at.vars, `${ctx}.art_template.vars`);
    for (const [k, v] of Object.entries(vars)) {
      if (typeof v !== "string") throw new Error(`${ctx}.art_template.vars[${k}] is not a string`);
    }
    item.art_template = { template_id: at.template_id, vars: vars as Record<string, string> };
  }

  return item;
}

export async function loadItems(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM items
  `;
  const map = new Map<string, Item>();
  for (const row of rows) {
    map.set(row.id, parseItemRow(row.id, row.data));
  }
  items = map;
  console.log(`Loaded ${map.size} items`);
}
