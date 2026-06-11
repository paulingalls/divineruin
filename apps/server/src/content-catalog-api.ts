import { listRoleArchetypes } from "./role_archetypes.ts";
import { listArchetypes } from "./archetypes.ts";
import { listAbilities } from "./abilities.ts";
import { listMilestones } from "./milestones.ts";

// Serves the four validation-only content catalogs (closes debt e43ada4fac62): each loader
// fail-loud-parses its rows at boot but had no production consumer — boot-green stood in for
// a real round-trip. One auth-gated dispatch endpoint gives all four a reader without four
// copy-pasted handlers; a new catalog is one registry line. Pure in-memory read, no DB.
// Map (not a plain object) so a name like "constructor"/"__proto__" can't resolve to an
// inherited member and slip past the 404 guard — Map.get returns undefined for any non-key.
const CATALOGS = new Map<string, () => readonly unknown[]>([
  ["role-archetypes", listRoleArchetypes],
  ["archetypes", listArchetypes],
  ["abilities", listAbilities],
  ["milestones", listMilestones],
]);

export function handleGetContentCatalog(name: string): Response {
  const accessor = CATALOGS.get(name);
  if (!accessor) {
    return Response.json({ error: `Unknown content catalog: ${name}` }, { status: 404 });
  }
  return Response.json({ catalog: name, items: accessor() });
}
