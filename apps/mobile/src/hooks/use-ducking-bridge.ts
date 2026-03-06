import { useEffect } from "react";
import { useVoiceAssistant } from "@livekit/react-native";
import { setDucking } from "@/audio/soundscape-player";

export function useDuckingBridge(): void {
  const { state } = useVoiceAssistant();

  useEffect(() => {
    setDucking(state === "speaking");
  }, [state]);
}
