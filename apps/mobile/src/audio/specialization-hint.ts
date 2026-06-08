/**
 * Sends the player's L5 specialization tap to the agent over the LiveKit data
 * channel ("player_hints" topic), mirroring use-creation-hints' send body.
 *
 * Kept livekit-free (the room is passed in, not pulled from a hook) so it is
 * unit-testable with a mock room. The specialization overlay calls this on tap
 * with the room from useMaybeRoomContext. A no-op without a room (e2e/no-room
 * safety). The agent's SpecializationTapHandler consumes SPECIALIZATION_CHOICE_TAP
 * (story-005) and drives the DM to resolve via the select verb — so the tap echoes
 * back the milestoneId it received in SPECIALIZATION_CHOICE (select needs the
 * choice_id, which the agent can't derive server-side).
 */

import type { Room } from "livekit-client";

import { SPECIALIZATION_CHOICE_TAP } from "./event-types";

const PLAYER_HINTS_TOPIC = "player_hints";

export function sendSpecializationChoice(
  room: Room | null | undefined,
  milestoneId: string,
  specializationId: string,
): void {
  if (!room) return;
  const payload = new TextEncoder().encode(
    JSON.stringify({
      type: SPECIALIZATION_CHOICE_TAP,
      milestone_id: milestoneId,
      specialization_id: specializationId,
    }),
  );
  void room.localParticipant.publishData(payload, {
    reliable: true,
    topic: PLAYER_HINTS_TOPIC,
  });
}
