import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "divineruin:volumes";

export type Bus = "master" | "voice" | "music" | "ambience" | "effects" | "ui";

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

const DEFAULTS: Record<Bus, number> = {
  master: 1.0,
  voice: 1.0,
  music: 0.7,
  ambience: 0.8,
  effects: 1.0,
  ui: 0.8,
};

const busVolumes: Record<Bus, number> = { ...DEFAULTS };

let persistTimer: ReturnType<typeof setTimeout> | null = null;

export function getVolume(bus: Bus): number {
  return busVolumes[bus];
}

export function getEffectiveVolume(bus: Bus): number {
  return busVolumes.master * busVolumes[bus];
}

export function setVolume(bus: Bus, value: number): void {
  busVolumes[bus] = clamp01(value);
  persistVolumes();
}

export async function loadVolumes(): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw) as Partial<Record<Bus, number>>;
    for (const key of Object.keys(DEFAULTS) as Bus[]) {
      if (typeof saved[key] === "number") {
        busVolumes[key] = clamp01(saved[key]);
      }
    }
  } catch {
    // Corrupted storage — keep defaults
  }
}

function persistVolumes(): void {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(busVolumes)).catch(() => {});
    persistTimer = null;
  }, 500);
}

/** Reset all volumes to defaults (for testing). */
export function _resetForTesting(): void {
  for (const key of Object.keys(DEFAULTS) as Bus[]) {
    busVolumes[key] = DEFAULTS[key];
  }
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
}

/** Flush any pending debounced persist (for testing). */
export function _flushPersistForTesting(): void {
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(busVolumes)).catch(() => {});
  }
}
