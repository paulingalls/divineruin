import type { DataChannelEvent } from "@/audio/game-event-handler";
import type { PanelTab } from "@/stores/panel-store";

declare global {
  interface Window {
    __DR?: {
      handleGameEvent: (event: DataChannelEvent) => void;
      openPanel: (tab: PanelTab) => void;
      closePanel: () => void;
    };
  }
}
