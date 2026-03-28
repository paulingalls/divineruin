// Web: re-export LiveKit hooks and components from @livekit/components-react
// Browsers have native WebRTC — no polyfills needed.
export {
  LiveKitRoom,
  useConnectionState,
  useLocalParticipant,
  useVoiceAssistant,
  useDataChannel,
  useMaybeRoomContext,
} from "@livekit/components-react";

export type { ReceivedDataMessage } from "@livekit/components-core";
