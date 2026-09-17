import type { ActiveStatus, TemplateGroup, TemplateItem } from "@divineruin/shared";

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
