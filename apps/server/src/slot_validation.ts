/**
 * Per-slot activity validation — pure functions, no IO. This is the AUTHORITATIVE
 * full slot model (3 slots + the Artificer exception). The Python agent does a
 * narrow companion-slot pre-check at dispatch (errand_tools._COMPANION_SLOT_CAP)
 * but does not reimplement the full model — dual validation, TS remains the source
 * of truth for slot counts + the Artificer exception.
 *
 * 3-independent-slot model: training (1 max), crafting (1 max), companion (1 max).
 * The Artificer exception (use the training slot for crafting when a Portable Lab
 * is equipped) is implemented here but NOT wired from production yet — deferred to
 * Phase 5 (see ADR 0005). The archetype/hasPortableLab params + their unit tests
 * are the Phase-5-ready seam.
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
