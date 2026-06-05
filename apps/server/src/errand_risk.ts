/**
 * Errand dispatch validation — pure functions, no IO except the startup loader.
 *
 * The TS server is the dispatch-time authority for errand danger levels and the
 * blocked-combo gate. It no longer rolls risk: the Python async worker rolls the
 * injury outcome at resolution (apps/agent/errand_risk.py, ADR 0006), since
 * nothing reads the outcome before then. BLOCKED_DANGER_COMBOS tracks
 * game_mechanics_core.md §Companion Risk (L887-892) — the same spec the Python
 * risk table conformance-pins against.
 *
 * Destination danger levels are derived at startup from the locations loaded by
 * locations.ts (listLocations()), so locations are the single SQL source — no
 * parallel query here. locations.json uses numeric danger_level values
 * (0=safe, 1=moderate, 2=dangerous, 3=extreme).
 */

import { listLocations } from "./locations.ts";
import { getErrandTemplate } from "./activity_templates.ts";

export type DangerLevel = "safe" | "moderate" | "dangerous" | "extreme";

// Runtime-loaded danger levels (populated by loadDestinationDangerLevels at startup)
let dangerLevels: ReadonlyMap<string, DangerLevel> = new Map();

export function getDangerLevel(destination: string): DangerLevel | undefined {
  return dangerLevels.get(destination);
}

// Test seam: inject a fixture map without going through the DB
export function setDestinationDangerLevels(map: ReadonlyMap<string, DangerLevel>): void {
  dangerLevels = map;
}

export function numericToDangerLevel(raw: string | number | null | undefined): DangerLevel {
  if (raw === null || raw === undefined || raw === "") return "safe";
  switch (String(raw)) {
    case "0":
      return "safe";
    case "1":
      return "moderate";
    case "2":
      return "dangerous";
    case "3":
      return "extreme";
    default:
      // Fail closed: an unknown value almost always means a typo in seed data.
      // Defaulting to "safe" would silently downgrade a dangerous destination
      // and bypass the errand restrictions in BLOCKED_DANGER_COMBOS.
      throw new Error(`numericToDangerLevel: unknown danger_level value ${String(raw)}`);
  }
}

// Derives the danger-level band map from the already-loaded locations. Pure and
// synchronous — call AFTER loadLocations() has populated the locations registry
// (index.ts startup). Replaces the former parallel `SELECT data->>'danger_level'
// FROM locations` so locations.ts is the single SQL read for location content.
export function loadDestinationDangerLevels(): void {
  const map = new Map<string, DangerLevel>();
  for (const loc of listLocations()) {
    map.set(loc.id, numericToDangerLevel(loc.danger_level));
  }
  dangerLevels = map;
  console.log(`Loaded danger levels for ${map.size} locations`);
}

// Blocked (danger_level, errand_type) combos — the spec's N/A cells (L887-892)
export const BLOCKED_DANGER_COMBOS: ReadonlySet<string> = new Set([
  "dangerous|relationship",
  "extreme|relationship",
  "extreme|social",
  "extreme|acquire",
]);

// Per-companion errand restrictions now live in the shared errand_templates
// content (each template's blocked_companions list), loaded into getErrandTemplate.

export interface ValidationResult {
  valid: boolean;
  error: string | null;
}

export function validateErrandDispatch(
  errandType: string,
  destination: string,
  companionId: string,
): ValidationResult {
  const dangerLevel = getDangerLevel(destination);
  if (dangerLevel === undefined) {
    return { valid: false, error: `Unknown destination: ${destination}` };
  }

  if (BLOCKED_DANGER_COMBOS.has(`${dangerLevel}|${errandType}`)) {
    return {
      valid: false,
      error: `${errandType} errands not available at ${dangerLevel} destinations`,
    };
  }

  if (getErrandTemplate(errandType)?.blocked_companions.includes(companionId)) {
    return {
      valid: false,
      error: `Companion ${companionId} cannot perform ${errandType} errands`,
    };
  }

  return { valid: true, error: null };
}
