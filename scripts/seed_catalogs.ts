import { parseLocationRow } from "../apps/server/src/locations.ts";
import { numericToDangerLevel } from "../apps/server/src/errand_risk.ts";
import { parseSpellCatalog, setSpells } from "../apps/server/src/spells.ts";
import { parseActivityTypeRows } from "../apps/server/src/training_state_machine.ts";
import { parseProgramRows, parseErrandRow } from "../apps/server/src/activity_templates.ts";
import { parseRecipeRow } from "../apps/server/src/recipes.ts";
import { parseItemRow } from "../apps/server/src/items.ts";
import { parseArchetypeRow } from "../apps/server/src/archetypes.ts";
import { parseAbilityRow } from "../apps/server/src/abilities.ts";
import { parseMentorVariantRow } from "../apps/server/src/mentor_variants.ts";
import {
  parseRoleArchetypeRow,
  validateRolePoolBinding,
} from "../apps/server/src/role_archetypes.ts";
import { parseMilestoneRow } from "../apps/server/src/milestones.ts";
import { parsePricingRow } from "../apps/server/src/pricing.ts";
import { merchantGoldAllocation } from "../apps/server/src/sale_pricing.ts";
import { boundInventoryPools, parseInventoryPools } from "../apps/server/src/inventory_pools.ts";

import { asRecord, parseString } from "../apps/server/src/parse-helpers.ts";

const snapshot = JSON.parse(await Bun.stdin.text()) as Record<
  string,
  { id: string; data: unknown }[]
>;
function rows(table: string) {
  const result = snapshot[table];
  if (!result?.length) throw new Error(`${table} produced no rows`);
  return result;
}
setSpells(
  parseSpellCatalog(
    rows("spells"),
    rows("creatures").map(({ id, data }) => ({
      id,
      category: asRecord(data, `creatures[${id}]`).category,
    })),
  ),
);
const types = parseActivityTypeRows(rows("training_activity_types"));
parseProgramRows(rows("training_programs"), types);
const itemIds = new Set(rows("items").map(({ id }) => id));
for (const { id, data } of rows("locations")) {
  numericToDangerLevel(parseLocationRow(id, data, itemIds).danger_level);
}
const parsers: [string, (id: string, data: unknown) => unknown][] = [
  ["errand_templates", parseErrandRow],
  ["recipes", parseRecipeRow],
  ["items", parseItemRow],
  ["archetypes", parseArchetypeRow],
  ["archetype_abilities", parseAbilityRow],
  ["mentor_variants", parseMentorVariantRow],
  ["archetype_milestones", parseMilestoneRow],
];
for (const [table, parse] of parsers) {
  for (const { id, data } of rows(table)) parse(id, data);
}

const pools = parseInventoryPools(rows("inventory_pools"), rows("items"));
const merchantPools = boundInventoryPools(rows("npcs"), pools);
const poolIds = new Set(pools.keys());
for (const { id, data } of rows("role_archetypes")) {
  validateRolePoolBinding(parseRoleArchetypeRow(id, data), poolIds);
}

const economy = rows("pricing").find(({ id }) => id === "economy");
if (!economy) throw new Error("pricing: no 'economy' row");
const pricing = parsePricingRow(economy.data, poolIds);
const locations = new Map(rows("locations").map(({ id, data }) => [id, data]));
for (const { id, data } of rows("npcs")) {
  const npc = asRecord(data, `npcs[${id}]`);
  const binding = npc.inventory_pool;
  if (typeof binding === "string") {
    const pool = merchantPools.get(binding)!;
    const field = `npcs[${id}].schedule`;
    const schedule = asRecord(npc.schedule, field);
    for (const locationId of new Set(
      Object.values(schedule).map((value) => parseString(value, field)),
    )) {
      merchantGoldAllocation(pool, locations.get(locationId), pricing, locationId);
    }
  }
}
