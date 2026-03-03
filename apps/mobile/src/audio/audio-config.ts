import { setAudioModeAsync } from "expo-audio";

let configPromise: Promise<void> | null = null;

export function configureAudioSession(): Promise<void> {
  if (!configPromise) {
    configPromise = setAudioModeAsync({
      playsInSilentMode: true,
      interruptionMode: "mixWithOthers",
    });
  }
  return configPromise;
}
