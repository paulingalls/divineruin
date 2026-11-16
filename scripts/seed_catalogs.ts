import { parseLocationRow } from "../apps/server/src/locations.ts";
import { numericToDangerLevel } from "../apps/server/src/errand_risk.ts";
import { parseSpellRow, setSpells } from "../apps/server/src/spells.ts";
import { parseActivityTypeRows } from "../apps/server/src/training_state_machine.ts";
import { parseProgramRows, parseErrandRow } from "../apps/server/src/activity_templates.ts";
import { parseRecipeRow } from "../apps/server/src/recipes.ts";
import { parseItemRow } from "../apps/server/src/items.ts";
import { parseArchetypeRow } from "../apps/server/src/archetypes.ts";
import { parseAbilityRow } from "../apps/server/src/abilities.ts";
import { parseMentorVariantRow } from "../apps/server/src/mentor_variants.ts";
import { parseRoleArchetypeRow } from "../apps/server/src/role_archetypes.ts";
import { parseMilestoneRow } from "../apps/server/src/milestones.ts";
import { parsePricingRow } from "../apps/server/src/pricing.ts";

const snapshot = JSON.parse(await Bun.stdin.text()) as Record<
  string,
  { id: string; data: unknown }[]
>;
function rows(table: string) {
  const result = snapshot[table];
  if (!result?.length) throw new Error(`${table} produced no rows`);
  return result;
}
setSpells(new Map(rows("spells").map(({ id, data }) => [id, parseSpellRow(id, data)])));
const types = parseActivityTypeRows(rows("training_activity_types"));
parseProgramRows(rows("training_programs"), types);
for (const { id, data } of rows("locations")) {
  numericToDangerLevel(parseLocationRow(id, data).danger_level);
}
const parsers: [string, (id: string, data: unknown) => unknown][] = [
  ["errand_templates", parseErrandRow],
  ["recipes", parseRecipeRow],
  ["items", parseItemRow],
  ["archetypes", parseArchetypeRow],
  ["archetype_abilities", parseAbilityRow],
  ["mentor_variants", parseMentorVariantRow],
  ["role_archetypes", parseRoleArchetypeRow],
  ["archetype_milestones", parseMilestoneRow],
  ["pricing", (_id, data) => parsePricingRow(data)],
];
for (const [table, parse] of parsers) {
  for (const { id, data } of rows(table)) parse(id, data);
}
