/**
 * The authored archetype corpus, with the floor constraint 12 demands on it.
 *
 * Both the shared-reader pin (archetype_tiers.test.ts) and the templates/start-route
 * parity walk (activity_spell_scope.test.ts) walk every row of this file, so the
 * "came back empty" and "ids are not unique" checks live here once: a second copy is
 * a second place for the floor to be weakened without the other noticing.
 */

import type { Archetype } from "@divineruin/shared";
import { parseArchetypeRow } from "../archetypes.ts";

const PATH = new URL("../../../../content/archetypes.json", import.meta.url);

const raw: unknown = await Bun.file(PATH).json();
if (!Array.isArray(raw) || raw.length === 0) {
  throw new Error("content/archetypes.json came back empty");
}
export const archetypeRows = raw as Record<string, unknown>[];

export function parseArchetypeCorpus(): Map<string, Archetype> {
  const parsed = new Map(
    archetypeRows.map((row) => {
      if (typeof row.id !== "string") throw new Error("archetype row id is not a string");
      return [row.id, parseArchetypeRow(row.id, row)] as const;
    }),
  );
  if (parsed.size !== archetypeRows.length)
    throw new Error("content/archetypes.json has duplicate ids");
  return parsed;
}
