import { test, expect, describe } from "bun:test";

// Capstone test for M5.0 (sprint-011 story-002): load content/items.json and
// prove every entry conforms to the widened Item interface from
// @divineruin/shared. Catches future drift between the TS contract and the
// JSON content — without this, a malformed entry would only fail at agent
// runtime (Python .get() returning None). See plan:
// /Users/paulingalls/.claude/plans/async-scribbling-valley.md
//
// Pattern: inline strict if/throw validation in the production-loader style
// of apps/server/src/activity_templates.ts:55-81 (parseProgramRow). Items are
// loaded as `unknown[]` and narrowed per-element so the defensive checks are
// real — casting to Item[] would let TS pre-narrow the type and turn the
// validation into a no-op. Helper extraction belongs at the production
// boundary (debt aa78e26e81a8 → M5.4).

const ITEMS_PATH = new URL("../../../content/items.json", import.meta.url);

// The 9 truly-required fields (per plan-reviewer concern e1ff500a86ad).
// `subtype, description, value_modifiers, lore, found_in` are originals-but-
// optional and walked separately.
const REQUIRED_FIELDS = [
  "id",
  "name",
  "tier",
  "type",
  "rarity",
  "tags",
  "weight",
  "effects",
  "value_base",
] as const;

const ALLOWED_TIERS = new Set([1, 2, 3, 4]);
const ALLOWED_DURABILITY_TIERS = new Set(["fragile", "standard", "reinforced", "masterwork"]);

async function loadItems(): Promise<unknown[]> {
  const raw: unknown = await Bun.file(ITEMS_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/items.json is not an array");
  return raw as unknown[];
}

function asRecord(entry: unknown, ctx: string): Record<string, unknown> {
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    throw new Error(`${ctx} is not an object`);
  }
  return entry as Record<string, unknown>;
}

// Floor for content/items.json size — currently 29 entries. Catches silent
// attrition from bad merges/rebases (a `length > 0` smoke would tolerate a
// drop from 29 to 3). One-entry tolerance leaves room for an intentional
// edit without forcing this constant to move on every legitimate change.
const MIN_ITEM_COUNT = 28;

describe("content/items.json — M5.0 widening conformance", () => {
  test("all entries have the 9 truly-required fields with correct types", async () => {
    const items = await loadItems();
    expect(items.length).toBeGreaterThanOrEqual(MIN_ITEM_COUNT);
    for (let i = 0; i < items.length; i++) {
      const ctx = `items.json[${i}]`;
      const item = asRecord(items[i], ctx);
      for (const field of REQUIRED_FIELDS) {
        if (!(field in item)) throw new Error(`${ctx}.${field} is missing`);
      }
      const idCtx = typeof item.id === "string" ? `items.json[${item.id}]` : ctx;
      if (typeof item.id !== "string") throw new Error(`${ctx}.id is not a string`);
      if (typeof item.name !== "string") throw new Error(`${idCtx}.name is not a string`);
      if (typeof item.tier !== "number") throw new Error(`${idCtx}.tier is not a number`);
      if (typeof item.type !== "string") throw new Error(`${idCtx}.type is not a string`);
      if (typeof item.rarity !== "string") throw new Error(`${idCtx}.rarity is not a string`);
      if (!Array.isArray(item.tags)) throw new Error(`${idCtx}.tags is not an array`);
      for (const tag of item.tags) {
        if (typeof tag !== "string") throw new Error(`${idCtx}.tags contains a non-string entry`);
      }
      if (typeof item.weight !== "number") throw new Error(`${idCtx}.weight is not a number`);
      if (!Array.isArray(item.effects)) throw new Error(`${idCtx}.effects is not an array`);
      for (let j = 0; j < item.effects.length; j++) {
        const effect = asRecord(item.effects[j], `${idCtx}.effects[${j}]`);
        // ItemEffect.type is the only required field (per packages/shared Item.ts).
        if (typeof effect.type !== "string")
          throw new Error(`${idCtx}.effects[${j}].type is not a string`);
        if (effect.target !== undefined && typeof effect.target !== "string")
          throw new Error(`${idCtx}.effects[${j}].target is not a string`);
        if (
          effect.value !== undefined &&
          typeof effect.value !== "number" &&
          typeof effect.value !== "string"
        )
          throw new Error(`${idCtx}.effects[${j}].value is not number or string`);
        if (effect.trigger !== undefined && typeof effect.trigger !== "string")
          throw new Error(`${idCtx}.effects[${j}].trigger is not a string`);
        if (effect.description !== undefined && typeof effect.description !== "string")
          throw new Error(`${idCtx}.effects[${j}].description is not a string`);
      }
      if (typeof item.value_base !== "number")
        throw new Error(`${idCtx}.value_base is not a number`);
    }
  });

  test("optional fields (when present) match the widened Item shape", async () => {
    const items = await loadItems();
    for (let i = 0; i < items.length; i++) {
      const item = asRecord(items[i], `items.json[${i}]`);
      const ctx = typeof item.id === "string" ? `items.json[${item.id}]` : `items.json[${i}]`;

      // Original optionals (pre-M5.0)
      if (item.subtype !== undefined && typeof item.subtype !== "string") {
        throw new Error(`${ctx}.subtype is not a string`);
      }
      if (item.description !== undefined && typeof item.description !== "string") {
        throw new Error(`${ctx}.description is not a string`);
      }
      if (item.lore !== undefined && typeof item.lore !== "string") {
        throw new Error(`${ctx}.lore is not a string`);
      }
      if (item.found_in !== undefined) {
        if (!Array.isArray(item.found_in)) {
          throw new Error(`${ctx}.found_in is not an array`);
        }
        for (const loc of item.found_in) {
          if (typeof loc !== "string")
            throw new Error(`${ctx}.found_in contains a non-string entry`);
        }
      }
      if (item.value_modifiers !== undefined) {
        const vm = asRecord(item.value_modifiers, `${ctx}.value_modifiers`);
        for (const [k, v] of Object.entries(vm)) {
          if (typeof v !== "number")
            throw new Error(`${ctx}.value_modifiers[${k}] is not a number`);
        }
      }

      // M5.0 new optionals
      if (
        item.durability_tier !== undefined &&
        (typeof item.durability_tier !== "string" ||
          !ALLOWED_DURABILITY_TIERS.has(item.durability_tier))
      ) {
        throw new Error(
          `${ctx}.durability_tier is not one of fragile|standard|reinforced|masterwork`,
        );
      }
      if (item.current_hits !== undefined && typeof item.current_hits !== "number") {
        throw new Error(`${ctx}.current_hits is not a number`);
      }
      if (item.damage_dice !== undefined && typeof item.damage_dice !== "string") {
        throw new Error(`${ctx}.damage_dice is not a string`);
      }
      if (item.properties !== undefined) {
        if (!Array.isArray(item.properties)) throw new Error(`${ctx}.properties is not an array`);
        for (const p of item.properties) {
          if (typeof p !== "string")
            throw new Error(`${ctx}.properties contains a non-string entry`);
        }
      }
      if (item.ac !== undefined && typeof item.ac !== "number") {
        throw new Error(`${ctx}.ac is not a number`);
      }
      if (item.armor_properties !== undefined) {
        if (!Array.isArray(item.armor_properties))
          throw new Error(`${ctx}.armor_properties is not an array`);
        for (const p of item.armor_properties) {
          if (typeof p !== "string")
            throw new Error(`${ctx}.armor_properties contains a non-string entry`);
        }
      }
      if (item.audio_cue !== undefined && typeof item.audio_cue !== "string") {
        throw new Error(`${ctx}.audio_cue is not a string`);
      }
      if (item.attunement !== undefined) {
        const at = asRecord(item.attunement, `${ctx}.attunement`);
        if (at.kind !== "none" && at.kind !== "required" && at.kind !== "class") {
          throw new Error(`${ctx}.attunement.kind is not none|required|class`);
        }
        if (at.kind === "class" && typeof at.class !== "string") {
          throw new Error(`${ctx}.attunement.class is required when kind is class`);
        }
      }
      if (item.quest_only !== undefined && typeof item.quest_only !== "boolean") {
        throw new Error(`${ctx}.quest_only is not a boolean`);
      }
      if (item.art_template !== undefined) {
        const at = asRecord(item.art_template, `${ctx}.art_template`);
        if (typeof at.template_id !== "string") {
          throw new Error(`${ctx}.art_template.template_id is not a string`);
        }
        const vars = asRecord(at.vars, `${ctx}.art_template.vars`);
        for (const [k, v] of Object.entries(vars)) {
          if (typeof v !== "string")
            throw new Error(`${ctx}.art_template.vars[${k}] is not a string`);
        }
      }
    }
  });

  test("all entries carry a tier within the widened 1|2|3|4 union", async () => {
    const items = await loadItems();
    for (let i = 0; i < items.length; i++) {
      const item = asRecord(items[i], `items.json[${i}]`);
      const ctx = typeof item.id === "string" ? `items.json[${item.id}]` : `items.json[${i}]`;
      if (typeof item.tier !== "number" || !ALLOWED_TIERS.has(item.tier)) {
        throw new Error(`${ctx}.tier=${String(item.tier)} is outside 1|2|3|4`);
      }
    }
  });
});
