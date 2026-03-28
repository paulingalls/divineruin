/**
 * Hook for sending card tap hints to the agent during character creation.
 *
 * Uses the LiveKit data channel on the "player_hints" topic.
 * Includes a 500ms debounce so rapid taps only send the last one.
 * Returns a no-op when rendered outside a LiveKit room (e.g. e2e tests).
 */

import { useCallback, useRef } from "react";

import { useMaybeRoomContext } from "@/livekit";
import { CREATION_CARD_TAP } from "@/audio/event-types";

const DEBOUNCE_MS = 500;
const PLAYER_HINTS_TOPIC = "player_hints";

export function useCreationHints() {
  const room = useMaybeRoomContext();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sendCreationHint = useCallback(
    (cardId: string, category: string) => {
      if (!room) return;
      if (timerRef.current) clearTimeout(timerRef.current);

      timerRef.current = setTimeout(() => {
        const payload = new TextEncoder().encode(
          JSON.stringify({
            type: CREATION_CARD_TAP,
            card_id: cardId,
            category,
          }),
        );
        void room.localParticipant.publishData(payload, {
          reliable: true,
          topic: PLAYER_HINTS_TOPIC,
        });
      }, DEBOUNCE_MS);
    },
    [room],
  );

  return { sendCreationHint };
}
