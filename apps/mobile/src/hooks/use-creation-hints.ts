/**
 * Hook for sending card tap hints to the agent during character creation.
 *
 * Uses the LiveKit data channel on the "player_hints" topic.
 * Includes a 500ms debounce so rapid taps only send the last one.
 */

import { useCallback, useRef } from "react";

import { useDataChannel } from "@/livekit";
import { CREATION_CARD_TAP } from "@/audio/event-types";

const DEBOUNCE_MS = 500;
const PLAYER_HINTS_TOPIC = "player_hints";

export function useCreationHints() {
  const { send } = useDataChannel(PLAYER_HINTS_TOPIC);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sendCreationHint = useCallback(
    (cardId: string, category: string) => {
      if (timerRef.current) clearTimeout(timerRef.current);

      timerRef.current = setTimeout(() => {
        const payload = JSON.stringify({
          type: CREATION_CARD_TAP,
          card_id: cardId,
          category,
        });
        void send(new TextEncoder().encode(payload), { reliable: true });
      }, DEBOUNCE_MS);
    },
    [send],
  );

  return { sendCreationHint };
}
