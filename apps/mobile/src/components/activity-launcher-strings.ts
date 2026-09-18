import type { ActiveStatus, TemplateGroup, TemplateItem } from "@divineruin/shared";

export type ActivityTemplatesState =
  | { kind: "loading" }
  | { kind: "ready"; groups: TemplateGroup[] }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string };

export async function getActivityTemplatesState(
  request: Promise<Response>,
): Promise<ActivityTemplatesState> {
  try {
    const response = await request;
    if (!response.ok) {
      return { kind: "error", message: "Activities are unavailable right now." };
    }
    const data = (await response.json()) as { groups?: unknown };
    if (!Array.isArray(data.groups)) {
      return { kind: "error", message: "Activities are unavailable right now." };
    }
    const groups = data.groups as TemplateGroup[];
    if (groups.length === 0) {
      return { kind: "empty", message: "No activities are available right now." };
    }
    return { kind: "ready", groups };
  } catch {
    return { kind: "error", message: "Activities are unavailable right now." };
  }
}

export type LaunchIntent =
  | { kind: "ready"; params: Record<string, unknown> }
  | { kind: "choose-spell"; spellIds: string[] }
  | { kind: "disabled"; reason: string };

export function getLaunchIntent(
  type: "crafting" | "training",
  item: TemplateItem,
  selectedSpellId?: string,
): LaunchIntent {
  if (type === "crafting") {
    return { kind: "ready", params: { recipe_id: item.params.recipe_id } };
  }
  const spellIdsRaw = item.params.studiable_spell_ids;
  if (spellIdsRaw === undefined) {
    return { kind: "ready", params: { program_id: item.params.program_id } };
  }
  if (
    !Array.isArray(spellIdsRaw) ||
    spellIdsRaw.some((id) => typeof id !== "string" || id.length === 0)
  ) {
    // The row disables itself rather than raising: getLaunchIntent runs during render for
    // every row, so a raise costs the player every other row too. Our own server is the
    // producer and nothing downstream records what it sent, so name it in the log as well.
    console.warn("[activity-launcher] malformed studiable_spell_ids:", item.id, spellIdsRaw);
    return { kind: "disabled", reason: "Spell choices are unavailable." };
  }
  const spellIds = spellIdsRaw as string[];
  if (spellIds.length === 0) {
    return { kind: "disabled", reason: "No spells available to study." };
  }
  if (selectedSpellId === undefined) return { kind: "choose-spell", spellIds };
  if (!spellIds.includes(selectedSpellId)) {
    throw new Error(`Selected spell ${selectedSpellId} is not available to study`);
  }
  return {
    kind: "ready",
    params: { program_id: item.params.program_id, spell_id: selectedSpellId },
  };
}

// The Bun lane's React Native mock omits View/Text, so testable presentation policy must
// stay outside activity-launcher.tsx.

/** "Lira is on a Scouting Run" — the busy banner for an in-flight companion errand. */
export function errandBusyLabel(companionName: string | null, activityName: string): string {
  return `${companionName ?? "Your companion"} is on a ${activityName}`;
}

export function trainingBusyLabel(activityName: string): string {
  return `Currently training: ${activityName}`;
}

export interface ActivityGroupState {
  isGroupLocked: boolean;
  activeItem: TemplateItem | undefined;
  groupBusy: boolean;
}

export function getActivityGroupState(group: TemplateGroup): ActivityGroupState {
  const isGroupLocked = group.type === "training" || group.type === "companion_errand";
  const activeItem = group.items.find((item) => item.active !== null);
  return {
    isGroupLocked,
    activeItem,
    groupBusy: isGroupLocked && activeItem !== undefined,
  };
}

export function isStartVisible(item: TemplateItem, groupState: ActivityGroupState): boolean {
  return item.active === null && !groupState.groupBusy;
}

/** "Where should Lira go?" — the destination picker's subtitle. */
export function errandDestinationPrompt(companionName: string | null): string {
  return `Where should ${companionName ?? "your companion"} go?`;
}

/** "2h 15m remaining" — the countdown on an in-flight activity. */
export function formatTimeRemaining(resolveAt: string): string {
  const remaining = new Date(resolveAt).getTime() - Date.now();
  if (remaining <= 0) return "completing...";
  const hours = Math.floor(remaining / 3_600_000);
  const minutes = Math.floor((remaining % 3_600_000) / 60_000);
  if (hours > 0) return `${hours}h ${minutes}m remaining`;
  return `${minutes}m remaining`;
}

export function activeText(active: ActiveStatus): string {
  if (active.isAwaitingDecision) return "waiting on you";
  return formatTimeRemaining(active.resolveAtEstimate);
}

export function mode(active: ActiveStatus): string {
  return active.isAwaitingDecision ? "WAITING" : "IN PROGRESS";
}
