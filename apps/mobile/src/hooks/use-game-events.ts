import { useDataChannel } from "@/livekit";
import { handleGameEventMessage } from "@/audio/game-event-handler";

export function useGameEvents(): void {
  useDataChannel("game_events", handleGameEventMessage);
}
