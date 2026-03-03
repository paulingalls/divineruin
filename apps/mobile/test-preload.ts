import { mock } from "bun:test";

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

mock.module("expo-audio", () => ({
  createAudioPlayer: (source: any) => ({
    volume: 1,
    play: () => {},
    remove: () => {},
    addListener: (_event: string, _cb: Function) => ({ remove: () => {} }),
  }),
  setAudioModeAsync: async () => {},
}));
