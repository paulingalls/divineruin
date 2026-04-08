/**
 * Errand risk computation — pure functions, no IO.
 *
 * Ports risk logic from Python errand_rules.py (lines 63-159).
 * Risk is rolled at dispatch time and stored in activity parameters
 * so the async worker only narrates the predetermined outcome.
 *
 * Danger levels are hardcoded here rather than read from locations.json.
 * locations.json uses numeric values (0=safe, 1=moderate, 2=dangerous, 3=extreme);
 * this mapping must be updated when new destinations are added.
 */

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

// Hardcoded danger levels — see file header comment for numeric mapping
export const DESTINATION_DANGER_LEVELS: Record<string, DangerLevel> = {
  millhaven: "safe",
  millhaven_inn: "safe",
  accord_guild_hall: "safe",
  accord_market_square: "moderate",
  accord_dockside: "moderate",
  greyvale_ruins_entrance: "dangerous",
};

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
  const dangerLevel = DESTINATION_DANGER_LEVELS[destination];
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
  const dangerLevel = DESTINATION_DANGER_LEVELS[destination] ?? "safe";
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
