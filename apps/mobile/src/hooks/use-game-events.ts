import { useDataChannel } from "@/livekit";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import type { ReceivedDataMessage } from "@/livekit";

export function useGameEvents(afterMessage?: (message: ReceivedDataMessage) => void): void {
  useDataChannel("game_events", (message) => {
    handleGameEventMessage(message);
    afterMessage?.(message);
  });
}
