/**
 * Sends the player's L5 specialization tap to the agent over the LiveKit data
 * channel ("player_hints" topic), mirroring use-creation-hints' send body.
 *
 * Kept livekit-free (the room is passed in, not pulled from a hook) so it is
 * unit-testable with a mock room. The specialization overlay calls this on tap
 * with the room from useMaybeRoomContext. A no-op without a room (e2e/no-room
 * safety). Agent-side consumption of SPECIALIZATION_CHOICE_TAP is a future
 * wire-up — the DM voice path already resolves via story-004's resolve_milestone.
 */

import type { Room } from "livekit-client";

import { SPECIALIZATION_CHOICE_TAP } from "./event-types";

const PLAYER_HINTS_TOPIC = "player_hints";

export function sendSpecializationChoice(
  room: Room | null | undefined,
  specializationId: string,
): void {
  if (!room) return;
  const payload = new TextEncoder().encode(
    JSON.stringify({
      type: SPECIALIZATION_CHOICE_TAP,
      specialization_id: specializationId,
    }),
  );
  void room.localParticipant.publishData(payload, {
    reliable: true,
    topic: PLAYER_HINTS_TOPIC,
  });
}
