export const DAMAGE_TYPES = [
  "acid",
  "bludgeoning",
  "cold",
  "fire",
  "force",
  "lightning",
  "necrotic",
  "piercing",
  "poison",
  "psychic",
  "radiant",
  "slashing",
  "thunder",
] as const;
export type DamageType = (typeof DAMAGE_TYPES)[number];
export interface DamageAffinities {
  resistant: DamageType[];
  immune: DamageType[];
  vulnerable: DamageType[];
}
const affinities = ["resistant", "immune", "vulnerable"] as const;
export function validateCreatureTraits(row: Record<string, unknown>): string[] {
  const problems: string[] = [];
  if ("resist_nonmagical_physical" in row && typeof row.resist_nonmagical_physical !== "boolean")
    problems.push("resist_nonmagical_physical: expected boolean");
  if ("unholy_fortitude" in row) {
    const spec = row.unholy_fortitude;
    if (typeof spec !== "object" || spec === null || Array.isArray(spec))
      problems.push("unholy_fortitude: expected object");
    else {
      const data = spec as Record<string, unknown>;
      const fields = ["save", "dc", "increment", "narration_cue"];
      for (const key of Object.keys(data))
        if (!fields.includes(key)) problems.push(`unholy_fortitude.${key}: unknown`);
      for (const key of fields) {
        const value = data[key];
        const valid =
          key === "save"
            ? ["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(value as string)
            : key === "narration_cue"
              ? typeof value === "string" && value.trim().length > 0
              : typeof value === "number" && Number.isInteger(value) && value > 0;
        if (!valid) problems.push(`unholy_fortitude.${key}: invalid`);
      }
    }
  }
  if ("damage_affinities" in row) {
    const traits = row.damage_affinities;
    if (typeof traits !== "object" || traits === null || Array.isArray(traits))
      problems.push("damage_affinities: expected object");
    else {
      const data = traits as Record<string, unknown>;
      const seen = new Set<string>();
      for (const key of Object.keys(data))
        if (!affinities.includes(key as (typeof affinities)[number]))
          problems.push(`damage_affinities.${key}: unknown affinity`);
      for (const key of affinities) {
        const path = `damage_affinities.${key}`;
        if (!(key in data)) {
          problems.push(`${path}: required`);
          continue;
        }
        const values = data[key];
        if (!Array.isArray(values)) {
          problems.push(`${path}: expected array`);
          continue;
        }
        const local = new Set<string>();
        values.forEach((value: unknown, i: number) => {
          if (typeof value !== "string" || !DAMAGE_TYPES.includes(value as DamageType))
            problems.push(`${path}[${i}]: expected damage type`);
          else if (local.has(value)) problems.push(`${path}: duplicate damage type`);
          else if (seen.has(value))
            problems.push(`damage_affinities: contradictory damage type ${value}`);
          else local.add(value);
        });
        for (const value of local) seen.add(value);
      }
    }
  }
  if ("tags" in row) {
    const tags = row.tags;
    if (!Array.isArray(tags)) problems.push("tags: expected array");
    else
      tags.forEach((tag: unknown, i: number) => {
        if (tag !== "plant") problems.push(`tags[${i}]: expected plant`);
        else if (tags.slice(0, i).includes(tag)) problems.push("tags: duplicate tag");
      });
  }
  return problems;
}
