import type {
  Milestone,
  MilestoneTier,
  MilestoneKind,
  SpecializationOption,
  Grant,
} from "@divineruin/shared";
import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded archetype milestones (M2.3). Mirrors abilities.ts: content/
// archetype_milestones.json -> archetype_milestones table, loaded at startup, parsed
// fail-loud, exposed via getMilestone/getArchetypeMilestones. The Python agent reads the
// same table (apps/agent/milestones.py); the archetype_milestones.json row IS the
// cross-language contract and each loader owns fail-loud validation. This parser stays
// structurally symmetric with Python parse_milestone_row. Records are self-contained
// (decision 4c0677dae1be): grants embed name/effect/flag, no FK into archetype_abilities.

const TIERS = new Set<MilestoneTier>(["identity", "power", "mastery", "legend"]);
const KINDS = new Set<MilestoneKind>(["specialization_fork", "auto_grant"]);

// Runtime-loaded milestones, keyed by milestone id (populated by loadMilestones at startup).
let milestones: ReadonlyMap<string, Milestone> = new Map();

// getMilestone is fail-loud (throws on unknown); getArchetypeMilestones is a list query
// returning [] for unknown — constraint m22-ability-accessor-semantics, mirroring Python.
export function getMilestone(id: string): Milestone {
  const milestone = milestones.get(id);
  if (!milestone) throw new Error(`Unknown milestone: ${id}`);
  return milestone;
}

export function getArchetypeMilestones(archetypeId: string): Milestone[] {
  return Array.from(milestones.values()).filter((m) => m.archetype_id === archetypeId);
}

export function setMilestones(map: ReadonlyMap<string, Milestone>): void {
  milestones = map;
}

export function listMilestones(): Milestone[] {
  return Array.from(milestones.values());
}

function parseOptions(raw: unknown, ctx: string): SpecializationOption[] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not an array`);
  return raw.map((opt, i) => {
    const o = asRecord(opt, `${ctx}[${i}]`);
    if (typeof o.id !== "string") throw new Error(`${ctx}[${i}].id is not a string`);
    if (typeof o.name !== "string") throw new Error(`${ctx}[${i}].name is not a string`);
    if (typeof o.description !== "string")
      throw new Error(`${ctx}[${i}].description is not a string`);
    return { id: o.id, name: o.name, description: o.description };
  });
}

function parseGrant(raw: unknown, ctx: string): Grant | null {
  if (raw === null) return null;
  const g = asRecord(raw, ctx);
  if (typeof g.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (typeof g.effect !== "string") throw new Error(`${ctx}.effect is not a string`);
  if (g.flag !== null && typeof g.flag !== "string") {
    throw new Error(`${ctx}.flag is not a string or null`);
  }
  return { name: g.name, effect: g.effect, flag: g.flag };
}

export function parseMilestoneRow(id: string, raw: unknown): Milestone {
  const data = asRecord(raw, `milestones[${id}]`);
  const ctx = `milestones[${id}]`;

  if (typeof data.archetype_id !== "string") throw new Error(`${ctx}.archetype_id is not a string`);
  if (typeof data.tier !== "string" || !TIERS.has(data.tier as MilestoneTier)) {
    throw new Error(`${ctx}.tier ${JSON.stringify(data.tier)} is invalid`);
  }
  if (typeof data.kind !== "string" || !KINDS.has(data.kind as MilestoneKind)) {
    throw new Error(`${ctx}.kind ${JSON.stringify(data.kind)} is invalid`);
  }
  // Integer (not just number) for parity with the Python loader, which requires an int
  // level (concern f499a5c2d1dd) — a shared row with a float level must fail identically
  // on both sides (the cross-language parity discipline from f3f1560feb6b).
  if (typeof data.level !== "number" || !Number.isInteger(data.level)) {
    throw new Error(`${ctx}.level is not an integer`);
  }
  if (typeof data.patron_deferred !== "boolean") {
    throw new Error(`${ctx}.patron_deferred is not a boolean`);
  }
  if (typeof data.narration_cue !== "string")
    throw new Error(`${ctx}.narration_cue is not a string`);

  return {
    id,
    archetype_id: data.archetype_id,
    tier: data.tier as MilestoneTier,
    level: data.level,
    kind: data.kind as MilestoneKind,
    patron_deferred: data.patron_deferred,
    specialization_options: parseOptions(
      data.specialization_options,
      `${ctx}.specialization_options`,
    ),
    grant: parseGrant(data.grant, `${ctx}.grant`),
    narration_cue: data.narration_cue,
  };
}

export async function loadMilestones(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM archetype_milestones
  `;
  // Build the local map then swap in one synchronous step, so a malformed row fails
  // loud WITHOUT wiping an already-loaded map (mirrors the Python loader's discipline).
  const map = new Map<string, Milestone>();
  for (const row of rows) {
    map.set(row.id, parseMilestoneRow(row.id, row.data));
  }
  milestones = map;
  console.log(`Loaded ${map.size} archetype milestones`);
}
