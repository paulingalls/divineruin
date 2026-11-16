import type { DataChannelEvent } from "@/audio/game-event-parsing";
import type { PanelTab } from "@/stores/panel-store";

declare global {
  interface Window {
    __DR?: {
      navigate: (path: "/" | "/session-test") => void;
      transport: {
        packets: { payload: number[]; reliable?: boolean; topic?: string }[];
        microphone: boolean[];
        disposed: boolean;
      };
      injectPacket: (payload: number[]) => void;
      startActivity: (type: string, parameters: Record<string, unknown>) => Promise<unknown>;
      submitDecision: (id: string, decision: string) => Promise<unknown>;
      inventory: () => { id: string; name: string; quantity: number }[];
      handleGameEvent: (event: DataChannelEvent) => void;
      openPanel: (tab: PanelTab) => void;
      closePanel: () => void;
    };
  }
}
