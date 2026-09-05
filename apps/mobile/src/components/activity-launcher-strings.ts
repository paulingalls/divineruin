/**
 * Display strings for the activity launcher that name the player's companion.
 *
 * A .ts, not part of activity-launcher.tsx, because the bun test lane's React Native mock
 * omits View/Text: a .tsx cannot be imported by any test here, so strings left inline in the
 * component are untestable.
 */

/** "Lira is on a Scouting Run" — the busy banner for an in-flight companion errand. */
export function errandBusyLabel(companionName: string | null, activityName: string): string {
  return `${companionName ?? "Your companion"} is on a ${activityName}`;
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
