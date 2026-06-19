// Dramatic-gate logic for the HUD dice overlay (story-006, M4.5). Kept in a .ts (not
// dice-roll-overlay.tsx) so the bun suite can unit-test it without react-native — the RN
// mock omits View/Text, so a .tsx import throws at module load (mirrors spell-display.ts).
//
// Scarcity is the whole point: the tumble-and-reveal animation only earns its weight if
// it fires 0-2 times per fight. The agent flags a high-stakes roll dramatic; everything
// else shows the result with no full animation. So the gate suppresses unless the payload
// EXPLICITLY carries dramatic === true — false, absent, or a non-boolean all suppress
// (scarcity-pure default). This is deliberately independent of the Hollow-Echo resonance
// band, which rides a separate event/overlay.

/**
 * True only when the dice payload explicitly flags the roll dramatic. False for
 * `dramatic: false`, an absent field, or any non-boolean value (defensive).
 */
export function isDramaticDicePayload(payload: Record<string, unknown>): boolean {
  return typeof payload.dramatic === "boolean" && payload.dramatic;
}
