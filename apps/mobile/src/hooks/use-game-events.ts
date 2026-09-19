import { useCallback } from "react";

import { useDataChannel } from "@/livekit";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import type { ReceivedDataMessage } from "@/livekit";

/** `afterMessage` observes every packet, including ones the DM-sender check drops. */
export function useGameEvents(afterMessage?: (message: ReceivedDataMessage) => void): void {
  // useDataChannel memoises its subscription on this callback's identity, so a
  // fresh closure per render would tear down and re-create the game_events
  // observable — packets arriving in that gap are lost. Callers must pass a
  // stable `afterMessage`.
  const onMessage = useCallback(
    (message: ReceivedDataMessage) => {
      handleGameEventMessage(message);
      afterMessage?.(message);
    },
    [afterMessage],
  );
  useDataChannel("game_events", onMessage);
}
