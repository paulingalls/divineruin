/**
 * Shared vertical anchors for bottom-mounted HUD elements.
 *
 * The XP toast, divine-favor toast, and combat tracker all sit at the same bottom
 * inset; the ResonanceTracker uses it as its default (lifting above the combat
 * tracker during combat). Centralizing the value here keeps those anchors in sync —
 * a layout shift is one edit, not four (concern 61cae1d5).
 */
export const HUD_ANCHORS = {
  /** Bottom inset (px) for full-width bottom toasts and the combat tracker. */
  bottomToast: 80,
} as const;
