/**
 * Errand risk computation — pure functions, no IO except the startup loader.
 *
 * Ports risk logic from Python errand_rules.py (lines 63-159).
 * Risk is rolled at dispatch time and stored in activity parameters
 * so the async worker only narrates the predetermined outcome.
 *
 * Destination danger levels are loaded from the locations table at startup
 * via loadDestinationDangerLevels(). locations.json uses numeric values
 * (0=safe, 1=moderate, 2=dangerous, 3=extreme).
 */

import { sql } from "./db.ts";

export type DangerLevel = "safe" | "moderate" | "dangerous" | "extreme";
export type InjuryStatus = "none" | "injured" | "emergency";

interface RiskEntry {
  injuryPct: number;
  emergencyPct: number;
}

// Matches Python ERRAND_RISK_TABLE (errand_rules.py lines 63-76)
const ERRAND_RISK_TABLE: Record<string, RiskEntry> = {
  "safe|scout": { injuryPct: 0, emergencyPct: 0 },
  "safe|social": { injuryPct: 0, emergencyPct: 0 },
  "safe|acquire": { injuryPct: 0, emergencyPct: 0 },
  "safe|relationship": { injuryPct: 0, emergencyPct: 0 },
  "moderate|scout": { injuryPct: 10, emergencyPct: 0 },
  "moderate|social": { injuryPct: 0, emergencyPct: 0 },
  "moderate|acquire": { injuryPct: 10, emergencyPct: 0 },
  "moderate|relationship": { injuryPct: 0, emergencyPct: 0 },
  "dangerous|scout": { injuryPct: 25, emergencyPct: 5 },
  "dangerous|social": { injuryPct: 0, emergencyPct: 0 },
  "dangerous|acquire": { injuryPct: 20, emergencyPct: 0 },
  "extreme|scout": { injuryPct: 40, emergencyPct: 15 },
};

// Injury risk reduction per companion (errand_rules.py lines 78-118)
const COMPANION_INJURY_REDUCTION: Record<string, number> = {
  companion_kael: 5,
};

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
      console.warn(
        `numericToDangerLevel: unknown danger_level value ${String(raw)}, defaulting to safe`,
      );
      return "safe";
  }
}

export async function loadDestinationDangerLevels(): Promise<void> {
  const rows = await sql<{ id: string; danger_level: string | null }[]>`
    SELECT id, data->>'danger_level' AS danger_level FROM locations
  `;
  const map = new Map<string, DangerLevel>();
  for (const row of rows) {
    map.set(row.id, numericToDangerLevel(row.danger_level));
  }
  dangerLevels = map;
  console.log(`Loaded danger levels for ${map.size} locations`);
}

// Blocked (danger_level, errand_type) combos — port of errand_rules.py:20-25
const BLOCKED_DANGER_COMBOS: ReadonlySet<string> = new Set([
  "dangerous|relationship",
  "extreme|relationship",
  "extreme|social",
  "extreme|acquire",
]);

// Per-companion errand restrictions — port of errand_rules.py blocked_errand_types.
// Companions not listed have no restrictions.
const COMPANION_BLOCKED_ERRAND_TYPES: Record<string, ReadonlySet<string>> = {
  companion_sable: new Set(["social", "relationship"]),
};

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

  if (COMPANION_BLOCKED_ERRAND_TYPES[companionId]?.has(errandType)) {
    return {
      valid: false,
      error: `Companion ${companionId} cannot perform ${errandType} errands`,
    };
  }

  return { valid: true, error: null };
}

export function rollErrandRisk(
  errandType: string,
  destination: string,
  companionId: string,
): InjuryStatus {
  const dangerLevel = getDangerLevel(destination) ?? "safe";
  const key = `${dangerLevel}|${errandType}`;
  const entry = ERRAND_RISK_TABLE[key];

  if (!entry || (entry.injuryPct === 0 && entry.emergencyPct === 0)) {
    return "none";
  }

  const roll = Math.floor(Math.random() * 100) + 1;
  const reduction = COMPANION_INJURY_REDUCTION[companionId] ?? 0;
  const effectiveInjury = Math.max(0, entry.injuryPct - reduction);

  if (roll <= entry.emergencyPct) {
    return "emergency";
  }
  if (roll <= entry.emergencyPct + effectiveInjury) {
    return "injured";
  }
  return "none";
}
