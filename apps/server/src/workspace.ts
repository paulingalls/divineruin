import type { Recipe } from "@divineruin/shared";

// Workspace access read path (M5.2). The server crafting gate (story-006) asks
// which workspaces a player can use at a location; rentals are persisted in the
// workspace_rentals table (migration 022) and read live (mutable, time-expiring
// per-player state — not startup-cached like static recipe content).

// The four workspaces. Reuses the closed structural enum already shared as
// Recipe["workspace_required"] — NOT DB-driven (it is rules structure, not
// authored content; both recipe loaders already anchor it against content).
export type WorkspaceType = Recipe["workspace_required"];

const WORKSPACE_TYPES = new Set<WorkspaceType>(["field", "workshop", "forge", "laboratory"]);

/** The universal floor: every player has Field access everywhere, never rented. */
export const FIELD: WorkspaceType = "field";

/**
 * Fail-loud parse of a workspace_rentals row's workspace_type. Rejects an
 * out-of-enum or non-string value at the DB boundary — a stray/typo'd type must
 * not silently widen crafting access. Mirrors recipes.ts WORKSPACES validation.
 */
export function parseWorkspaceType(raw: unknown, ctx: string): WorkspaceType {
  if (typeof raw !== "string" || !WORKSPACE_TYPES.has(raw as WorkspaceType)) {
    throw new Error(`${ctx} ${String(raw)} is not a valid workspace type`);
  }
  return raw as WorkspaceType;
}
