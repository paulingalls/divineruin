import { sql } from "./db.ts";

export type AssignedCompanion =
  | { ok: true; companionId: string }
  | { ok: false; status: 400 | 500; error: string };

/**
 * The companion assigned to a player — the complement of their archetype, the same rule the
 * agent's session start hydrates. Never a caller-supplied or defaulted id, which is what let a
 * Sable player past a Sable-only block. Mirrors errand_tools._dispatch_companion_errand_impl.
 *
 * One resolution, two callers (errand dispatch and the catch-up feed). Callers decide what a
 * failure costs them: dispatch returns the status verbatim, the feed drops a cosmetic line.
 */
export async function resolveAssignedCompanion(playerId: string): Promise<AssignedCompanion> {
  const playerRows = await sql<{ class: string | null }[]>`
    SELECT data->>'class' AS class FROM players WHERE player_id = ${playerId}
  `;
  const archetype = playerRows[0]?.class;
  if (!archetype) {
    return { ok: false, status: 400, error: "Player has no class; cannot dispatch an errand" };
  }

  const complementRows = await sql<{ id: string }[]>`
    SELECT id FROM companions WHERE data->'complements' ? ${archetype}
  `;
  if (complementRows.length !== 1) {
    return {
      ok: false,
      status: 500,
      error: `Archetype ${archetype} matches ${complementRows.length} companions`,
    };
  }
  return { ok: true, companionId: complementRows[0]!.id };
}
