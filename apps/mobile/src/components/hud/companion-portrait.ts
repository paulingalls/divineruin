import type { CombatTrackerState } from "@/stores/hud-store";

interface CompanionPortraitSelection {
  companionVisible: boolean;
  companionPrimaryUrl: string | null;
  companionAlertUrl: string | null;
  combatState: CombatTrackerState | null;
}

export function selectCompanionPortrait(selection: CompanionPortraitSelection): string | null {
  if (!selection.companionVisible) return null;
  return selection.combatState === null
    ? selection.companionPrimaryUrl
    : selection.companionAlertUrl;
}
