import { setAudioModeAsync } from "expo-audio";

let configPromise: Promise<void> | null = null;

export function configureAudioSession(): Promise<void> {
  if (!configPromise) {
    configPromise = setAudioModeAsync({
      playsInSilentMode: true,
      interruptionMode: "mixWithOthers",
      // allowsRecording enables iOS .playAndRecord category — required for
      // LiveKit WebRTC voice + local audio playback to coexist.
      allowsRecording: true,
      shouldRouteThroughEarpiece: false,
    });
  }
  return configPromise;
}
