import { DAMAGE_TYPES } from "./creature_damage_affinity";

export interface CorruptionField {
  save: "STR" | "DEX" | "CON" | "INT" | "WIS" | "CHA";
  dc: number;
  damage: string;
  damage_type: (typeof DAMAGE_TYPES)[number];
}
export interface Regeneration {
  hp: number;
  narration_cue: string;
  suppressed_cue: string;
  resumed_cue: string;
}
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
export function validateTurnTraits(row: Record<string, unknown>): string[] {
  const problems: string[] = [];
  const fields = {
    corruption_field: ["save", "dc", "damage", "damage_type"],
    regeneration: ["hp", "narration_cue", "suppressed_cue", "resumed_cue"],
  };
  if (Object.keys(fields).some((key) => key in row) && row.id !== "hollow_veilrender")
    problems.push("turn traits: require Veilrender catalog owner");
  for (const [key, keys] of Object.entries(fields)) {
    if (!(key in row)) continue;
    const spec = row[key];
    if (!object(spec) || Object.keys(spec).sort().join() !== [...keys].sort().join()) {
      problems.push(`${key}: invalid fields`);
      continue;
    }
    for (const [name, value] of Object.entries(spec)) {
      const valid = ["hp", "dc"].includes(name)
        ? typeof value === "number" && Number.isInteger(value) && value > 0
        : name === "save"
          ? ["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(value as string)
          : name === "damage"
            ? typeof value === "string" && /^[1-9][0-9]*d[1-9][0-9]*(?:[+-][0-9]+)?$/.test(value)
            : name === "damage_type"
              ? (DAMAGE_TYPES as readonly unknown[]).includes(value)
              : typeof value === "string" && value.trim().length > 0;
      if (!valid) problems.push(`${key}.${name}: invalid`);
    }
    if (key === "corruption_field") {
      const radius = object(row.hollow) ? row.hollow.corruption_aura : undefined;
      if (typeof radius !== "number" || !Number.isInteger(radius) || radius <= 0)
        problems.push("corruption_field: requires positive hollow.corruption_aura");
    }
  }
  return problems;
}
