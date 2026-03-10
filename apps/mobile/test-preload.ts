import { mock } from "bun:test";

// React Native sets __DEV__ at build time; define it for the test environment.
(globalThis as any).__DEV__ = true;

// React Native's entry point uses Flow syntax that Bun can't parse.
// Mock it and other native modules before any test files load.
mock.module("react-native", () => ({
  Platform: { OS: "ios" },
  StyleSheet: { create: (s: any) => s },
  NativeModules: {},
}));

mock.module("@react-native-async-storage/async-storage", () => {
  let store: Record<string, string> = {};
  return {
    default: {
      getItem: async (key: string) => store[key] ?? null,
      setItem: async (key: string, value: string) => {
        store[key] = value;
      },
      _clear: () => {
        store = {};
      },
    },
  };
});

mock.module("expo-haptics", () => ({
  impactAsync: async () => {},
  notificationAsync: async () => {},
  ImpactFeedbackStyle: { Light: "light", Medium: "medium", Heavy: "heavy" },
  NotificationFeedbackType: { Success: "success", Warning: "warning", Error: "error" },
}));

mock.module("expo-audio", () => ({
  createAudioPlayer: (source: any) => ({
    volume: 1,
    play: () => {},
    remove: () => {},
    addListener: (_event: string, _cb: Function) => ({ remove: () => {} }),
  }),
  setAudioModeAsync: async () => {},
}));
