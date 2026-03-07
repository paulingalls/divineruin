import { useEffect } from "react";
import { useVoiceAssistant } from "@livekit/react-native";
import { setDucking } from "@/audio/soundscape-player";
import { setMusicDucking } from "@/audio/music-player";

export function useDuckingBridge(): void {
  const { state } = useVoiceAssistant();

  useEffect(() => {
    const speaking = state === "speaking";
    setDucking(speaking);
    setMusicDucking(speaking);
  }, [state]);
}
