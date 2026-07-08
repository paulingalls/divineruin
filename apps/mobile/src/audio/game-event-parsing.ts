import type { MusicState } from "./music-registry";
import { HOLLOW_ECHO_DISPLAY } from "@/stores/hud-store";
import type { Combatant, Condition, HollowEchoBand, ResonanceState } from "@/stores/hud-store";
import type { InventoryItem, ItemRarity } from "@/stores/panel-store";
import type { CombatDifficulty } from "@/stores/session-store";

export interface DataChannelEvent {
  type: string;
  [key: string]: unknown;
}

const decoder = new TextDecoder();

export const VALID_RARITIES = new Set<ItemRarity>(["common", "uncommon", "rare", "legendary"]);

export const VALID_MUSIC_STATES = new Set<MusicState>([
  "silence",
  "exploration",
  "tension",
  "combat_standard",
  "combat_boss",
  "wonder",
  "sorrow",
  "hollow_dissolution",
  "title",
]);

export const VALID_DIFFICULTIES = new Set<CombatDifficulty>(["moderate", "hard"]);

export const VALID_RESONANCE_STATES = new Set<ResonanceState>([
  "stable",
  "flickering",
  "overreach",
]);

// The 7 Hollow Echo bands (M3.2) — derived from HOLLOW_ECHO_DISPLAY so the band list
// has a single runtime source of truth (the HollowEchoBand union types the keys). An
// echo payload whose band isn't one of these is dropped (fail-safe), never rendered.
export const VALID_HOLLOW_ECHO_BANDS = new Set<HollowEchoBand>(
  Object.keys(HOLLOW_ECHO_DISPLAY) as HollowEchoBand[],
);

export function parseRarity(value: unknown): ItemRarity {
  return typeof value === "string" && VALID_RARITIES.has(value as ItemRarity)
    ? (value as ItemRarity)
    : "common";
}

export function parseInventoryItems(rawItems: Record<string, unknown>[]): InventoryItem[] {
  return rawItems.map((raw) => {
    const slotInfo = raw.slot_info as Record<string, unknown> | undefined;
    return {
      id: typeof raw.id === "string" ? raw.id : "",
      name: typeof raw.name === "string" ? raw.name : "",
      type: typeof raw.type === "string" ? raw.type : "",
      rarity: parseRarity(raw.rarity),
      description: typeof raw.description === "string" ? raw.description : "",
      weight: typeof raw.weight === "number" ? raw.weight : 0,
      effects: Array.isArray(raw.effects) ? (raw.effects as Record<string, unknown>[]) : [],
      lore: typeof raw.lore === "string" ? raw.lore : "",
      value_base: typeof raw.value_base === "number" ? raw.value_base : 0,
      quantity: typeof slotInfo?.quantity === "number" ? slotInfo.quantity : 1,
      equipped: slotInfo?.equipped === true,
      ...(typeof raw.image_url === "string" ? { imageUrl: raw.image_url } : {}),
    };
  });
}

export function parseCondition(raw: unknown): Condition | null {
  if (typeof raw !== "object" || raw === null) return null;
  const c = raw as Record<string, unknown>;
  if (typeof c.type !== "string") return null;
  return {
    type: c.type,
    stacks: typeof c.stacks === "number" ? c.stacks : 1,
    source: typeof c.source === "string" ? c.source : "",
  };
}

export function parseCombatant(raw: unknown): Combatant | null {
  if (typeof raw !== "object" || raw === null) return null;
  const c = raw as Record<string, unknown>;
  if (typeof c.id !== "string" || typeof c.name !== "string") return null;
  const conditions = Array.isArray(c.conditions)
    ? c.conditions.map(parseCondition).filter((x): x is Condition => x !== null)
    : [];
  return {
    id: c.id,
    name: c.name,
    isAlly: typeof c.isAlly === "boolean" ? c.isAlly : false,
    hpCurrent: typeof c.hpCurrent === "number" ? c.hpCurrent : 0,
    hpMax: typeof c.hpMax === "number" ? c.hpMax : 1,
    conditions,
    isActive: typeof c.isActive === "boolean" ? c.isActive : false,
  };
}

export function extractExitConnections(exits: Record<string, unknown>): string[] {
  const connections: string[] = [];
  for (const exitData of Object.values(exits)) {
    if (typeof exitData === "string") {
      if (exitData) connections.push(exitData);
    } else if (exitData && typeof exitData === "object") {
      const dest = (exitData as Record<string, unknown>).destination;
      if (typeof dest === "string" && dest) connections.push(dest);
    }
  }
  return connections;
}

/** Maximum payload size for data channel messages (1 MB). */
export const MAX_EVENT_PAYLOAD_BYTES = 1_048_576;

export function parseGameEvent(payload: Uint8Array): DataChannelEvent | null {
  if (payload.length > MAX_EVENT_PAYLOAD_BYTES) return null;
  try {
    const text = decoder.decode(payload);
    const data: unknown = JSON.parse(text);
    if (data && typeof data === "object" && "type" in data) {
      return data as DataChannelEvent;
    }
    console.warn("[game-events] Missing type field:", data);
    return null;
  } catch {
    console.warn("[game-events] Failed to parse message");
    return null;
  }
}
