import type { Spell, SpellSource, SpellTier } from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded spell catalog (M8 / story-001). Mirrors abilities.ts: content/spells.json
// -> spells table, loaded at startup, parsed fail-loud, exposed via getSpell/
// getSpellsBySource. The Python agent reads the same table (apps/agent/spells.py); the
// spells.json row IS the cross-language contract and each loader owns fail-loud
// validation. This parser stays structurally symmetric with Python parse_spell_row.
//
// SOURCE-keyed. M3.3 makes spells.json the FULL casting-data SSOT (decision
// spell-catalog-full-casting-ssot), superseding the M8 elective-only seam (235ae150c5d3):
// caster core spells now live in the catalog too (archetype_abilities `core` rows stay as
// the access grant). This TS loader stays lenient — the M3.3 fields (resonance_by_source,
// audio_cue, concentration) are still ignored here; mirroring Python's strict-require +
// int-value validation is tracked as concern 26ab12def2a3.

const SPELL_SOURCES = new Set<SpellSource>(["arcane", "divine", "primal"]);
const SPELL_TIERS = new Set<SpellTier>(["cantrip", "minor", "standard", "major", "supreme"]);

// Runtime-loaded spells, keyed by spell id (populated by loadSpells at startup).
let spells: ReadonlyMap<string, Spell> = new Map();

// getSpell is fail-loud (raises on unknown); getSpellsBySource is a list query
// returning [] for unknown — mirroring Python get_spell / get_spells_by_source.
export function getSpell(id: string): Spell {
  const spell = spells.get(id);
  if (!spell) throw new Error(`Unknown spell: ${id}`);
  return spell;
}

export function getSpellsBySource(source: string): Spell[] {
  return Array.from(spells.values()).filter((s) => s.source === source);
}

export function listSpells(): Spell[] {
  return Array.from(spells.values());
}

export function setSpells(map: ReadonlyMap<string, Spell>): void {
  spells = map;
}

function requireInteger(value: unknown, ctx: string): number {
  // Integer (not just number) for parity with the Python loader's _require_int, which
  // requires int — a shared row with a float must fail identically on both sides.
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${ctx} is not an integer`);
  }
  return value;
}

function positiveInteger(raw: unknown, ctx: string): number {
  const value = requireInteger(raw, ctx);
  if (value < 1) throw new Error(`${ctx} must be positive`);
  return value;
}

function parseWildShape(raw: unknown, ctx: string): NonNullable<Spell["wild_shape"]> {
  const profile = asRecord(raw, ctx);
  const stamina_cost = positiveInteger(profile.stamina_cost, `${ctx}.stamina_cost`);
  if (!Array.isArray(profile.forms) || profile.forms.length === 0) {
    throw new Error(`${ctx}.forms must be a nonempty list`);
  }
  const seen = new Set<string>();
  const forms = profile.forms.map((raw: unknown) => {
    const { creature_id, min_level } = asRecord(raw, `${ctx}.forms entry`);
    if (typeof creature_id !== "string" || !creature_id.trim() || seen.has(creature_id)) {
      throw new Error(
        `${ctx} has an invalid or repeated creature id ${JSON.stringify(creature_id)}`,
      );
    }
    seen.add(creature_id);
    return {
      creature_id,
      min_level: positiveInteger(min_level, `${ctx}.${creature_id}.min_level`),
    };
  });
  return { stamina_cost, forms };
}

export function parseSpellRow(id: string, raw: unknown): Spell {
  const data = asRecord(raw, `spells[${id}]`);
  const ctx = `spells[${id}]`;

  if (typeof data.source !== "string" || !SPELL_SOURCES.has(data.source as SpellSource)) {
    throw new Error(`${ctx}.source ${JSON.stringify(data.source)} is invalid`);
  }
  if (typeof data.spell_tier !== "string" || !SPELL_TIERS.has(data.spell_tier as SpellTier)) {
    throw new Error(`${ctx}.spell_tier ${JSON.stringify(data.spell_tier)} is invalid`);
  }
  if (typeof data.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof data.mechanics !== "string") throw new Error(`${ctx}.mechanics is not a string`);
  if (typeof data.narration_cue !== "string") {
    throw new Error(`${ctx}.narration_cue is not a string`);
  }

  for (const field of ["verbal", "hostile"] as const) {
    if (typeof data[field] !== "boolean") throw new Error(`${ctx}.${field} is not a boolean`);
  }

  return {
    id,
    name: data.name,
    source: data.source as SpellSource,
    spell_tier: data.spell_tier as SpellTier,
    focus_cost: requireInteger(data.focus_cost, `${ctx}.focus_cost`),
    mechanics: data.mechanics,
    narration_cue: data.narration_cue,
    verbal: data.verbal as boolean,
    hostile: data.hostile as boolean,
    ...(id === "primal_wild_shape" || "wild_shape" in data
      ? { wild_shape: parseWildShape(data.wild_shape, `${ctx}.wild_shape`) }
      : {}),
  };
}

export function parseSpellCatalog(
  rows: { id: string; data: unknown }[],
  creatures: { id: string; category: unknown }[],
): Map<string, Spell> {
  const beastIds = new Set(
    creatures.filter((row) => row.category === "beast").map((row) => row.id),
  );
  const map = new Map<string, Spell>();
  for (const { id, data } of rows) {
    const spell = parseSpellRow(id, data);
    for (const { creature_id } of spell.wild_shape?.forms ?? []) {
      if (!beastIds.has(creature_id)) {
        throw new Error(
          `spells[${id}].wild_shape creature '${creature_id}' must name a catalog beast`,
        );
      }
    }
    map.set(id, spell);
  }
  return map;
}

export async function loadSpells(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`SELECT id, data FROM spells`;
  const creatures = await sql<{ id: string; category: string }[]>`
    SELECT id, data->>'category' AS category FROM creatures
  `;
  const map = parseSpellCatalog(rows, creatures);
  setSpells(map);
  console.log(`Loaded ${map.size} spells`);
}
