import type { Spell, SpellSource, SpellTier } from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded spell catalog (M8 / story-001). Mirrors abilities.ts: content/spells.json
// -> spells table, loaded at startup, parsed fail-loud, exposed via getSpell/
// getSpellsBySource. The Python agent reads the same table (apps/agent/spells.py); the
// spells.json row IS the cross-language contract and each loader owns fail-loud
// validation. This parser stays structurally symmetric with Python parse_spell_row.
//
// SOURCE-keyed, not archetype-keyed: caster CORE spells stay archetype_abilities rows
// (ability_type=core, seam 235ae150c5d3); this catalog is the ELECTIVE library only.
// Borrows Phase-3 Magic's M3.3 schema minimally — extra JSONB fields are ignored here.

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

  return {
    id,
    name: data.name,
    source: data.source as SpellSource,
    spell_tier: data.spell_tier as SpellTier,
    level_requirement: requireInteger(data.level_requirement, `${ctx}.level_requirement`),
    focus_cost: requireInteger(data.focus_cost, `${ctx}.focus_cost`),
    mechanics: data.mechanics,
    narration_cue: data.narration_cue,
  };
}

export async function loadSpells(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM spells
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails
  // loud WITHOUT wiping an already-loaded map (mirrors the Python loader's discipline).
  const map = new Map<string, Spell>();
  for (const row of rows) {
    map.set(row.id, parseSpellRow(row.id, row.data));
  }
  spells = map;
  console.log(`Loaded ${map.size} spells`);
}
