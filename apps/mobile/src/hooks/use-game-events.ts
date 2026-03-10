import { useCallback } from "react";
import { useDataChannel, type ReceivedDataMessage } from "@/livekit";
import { parseGameEvent, handleGameEvent } from "@/audio/game-event-handler";

export function useGameEvents(): void {
  const onMessage = useCallback((msg: ReceivedDataMessage) => {
    const event = parseGameEvent(msg.payload);
    if (event) handleGameEvent(event);
  }, []);

  useDataChannel("game_events", onMessage);
}
