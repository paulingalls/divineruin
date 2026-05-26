import type { Recipe } from "@divineruin/shared";

import { sql } from "./db.ts";

// Workspace access read path (M5.2). The server crafting gate (story-006) asks
// which workspaces a player can use at a location; rentals are persisted in the
// workspace_rentals table (migration 022) and read live (mutable, time-expiring
// per-player state — not startup-cached like static recipe content).

// The four workspaces. Reuses the closed structural enum already shared as
// Recipe["workspace_required"] — NOT DB-driven (it is rules structure, not
// authored content; both recipe loaders already anchor it against content).
export type WorkspaceType = Recipe["workspace_required"];

// The single TS runtime source of the workspace vocabulary (symmetric with
// apps/agent/workspace.py, the Python SSOT). recipes.ts imports this rather than
// keeping its own copy, so a future 5th workspace is added in exactly one place.
export const WORKSPACE_TYPES = new Set<WorkspaceType>(["field", "workshop", "forge", "laboratory"]);

/** The universal floor: every player has Field access everywhere, never rented. */
export const FIELD: WorkspaceType = "field";

/**
 * Fail-loud parse of a workspace_rentals row's workspace_type. Rejects an
 * out-of-enum or non-string value at the DB boundary — a stray/typo'd type must
 * not silently widen crafting access. recipes.ts validates the same way against
 * the shared WORKSPACE_TYPES exported here.
 */
export function parseWorkspaceType(raw: unknown, ctx: string): WorkspaceType {
  if (typeof raw !== "string" || !WORKSPACE_TYPES.has(raw as WorkspaceType)) {
    throw new Error(`${ctx} ${String(raw)} is not a valid workspace type`);
  }
  return raw as WorkspaceType;
}

/**
 * The workspace types a player can use AT THIS LOCATION right now. Always
 * includes "field" (the universal floor). Adds each ACTIVE, location-bound
 * rental's workspace_type — active = no expiry (standing access) or not yet
 * expired. A live DB read, not a startup cache: rentals are written mid-session
 * and expire over wall-clock time, so a cached view would mis-gate.
 *
 * `locationId` is passed in because a player's current location is agent session
 * state, not a server-queryable column; the crafting gate (story-006) supplies
 * it from the request.
 *
 * `opts.hasPortableLab` (story-006): an Artificer's Portable Lab grants Workshop +
 * basic Laboratory ANYWHERE — the location-agnostic `source = 'portable'` grant the
 * single-location rental filter was built to extend. It does NOT grant Forge. The
 * caller reads ownership once (player_inventory) and passes it here AND to the slot
 * validator, so the inventory row is read a single time.
 */
export async function accessibleWorkspaceTier(
  playerId: string,
  locationId: string,
  opts?: { hasPortableLab?: boolean },
): Promise<Set<WorkspaceType>> {
  const rows = await sql<{ workspace_type: unknown }[]>`
    SELECT workspace_type FROM workspace_rentals
    WHERE player_id = ${playerId}
      AND location_id = ${locationId}
      AND (expires_at IS NULL OR expires_at > NOW())
  `;

  const tiers = new Set<WorkspaceType>([FIELD]);
  for (const row of rows) {
    tiers.add(parseWorkspaceType(row.workspace_type, "workspace_rentals.workspace_type"));
  }
  if (opts?.hasPortableLab) {
    tiers.add("workshop");
    tiers.add("laboratory");
  }
  return tiers;
}
