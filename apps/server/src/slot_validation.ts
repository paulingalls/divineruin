/**
 * Per-slot activity validation — pure functions, no IO.
 *
 * Mirrors Python errand_rules.validate_slot_limits() with the 3-independent-slot model:
 *   training (1 max), crafting (1 max), companion (1 max)
 * Artificer exception: can use training slot for crafting when portable_lab equipped.
 */

import type { ActivityType } from "@divineruin/shared";

export type ActivitySlot = "training" | "crafting" | "companion";

export interface SlotCounts {
  training: number;
  crafting: number;
  companion: number;
}

export interface SlotValidationResult {
  valid: boolean;
  error: string | null;
}

const ACTIVITY_TYPE_TO_SLOT: Record<ActivityType, ActivitySlot> = {
  training: "training",
  crafting: "crafting",
  companion_errand: "companion",
};

export function activityTypeToSlot(activityType: string): ActivitySlot | null {
  if (activityType in ACTIVITY_TYPE_TO_SLOT) {
    return ACTIVITY_TYPE_TO_SLOT[activityType as ActivityType];
  }
  return null;
}

export function validateSlotAvailability(
  slotCounts: SlotCounts,
  activityType: string,
  archetype?: string,
  hasPortableLab?: boolean,
): SlotValidationResult {
  const slot = activityTypeToSlot(activityType);
  if (slot === null) {
    return { valid: false, error: `Invalid activity type: ${activityType}` };
  }

  const current = slotCounts[slot];

  if (slot === "crafting" && current >= 1) {
    // Artificer exception: can use training slot for crafting
    if (archetype?.toLowerCase() === "artificer" && hasPortableLab) {
      if (slotCounts.training >= 1) {
        return { valid: false, error: "Both crafting and training slots are full" };
      }
      return { valid: true, error: null };
    }
    return { valid: false, error: "Crafting slot is full" };
  }

  if (current >= 1) {
    const label = slot.charAt(0).toUpperCase() + slot.slice(1);
    return { valid: false, error: `${label} slot is full` };
  }

  return { valid: true, error: null };
}
