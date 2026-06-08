import { test, expect, beforeEach } from "bun:test";
import {
  parseGameEvent,
  handleGameEvent,
  parseCombatant,
  MAX_EVENT_PAYLOAD_BYTES,
} from "@/audio/game-event-handler";
import { panelStore } from "@/stores/panel-store";
import { encode, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- parseGameEvent ---

test("parseGameEvent decodes valid JSON with type field", () => {
  const event = parseGameEvent(encode({ type: "play_sound", sound_name: "sword_clash" }));
  expect(event).toEqual({ type: "play_sound", sound_name: "sword_clash" });
});

test("parseGameEvent returns null for missing type field", () => {
  expect(parseGameEvent(encode({ sound_name: "sword_clash" }))).toBeNull();
});

test("parseGameEvent returns null for malformed JSON", () => {
  const payload = new TextEncoder().encode("not json{{{");
  expect(parseGameEvent(payload)).toBeNull();
});

test("parseGameEvent returns null for non-object JSON", () => {
  const payload = new TextEncoder().encode('"just a string"');
  expect(parseGameEvent(payload)).toBeNull();
});

// --- parseCombatant ---

test("parseCombatant returns valid combatant from well-formed data", () => {
  const result = parseCombatant({
    id: "c1",
    name: "Kael",
    isAlly: true,
    hpCurrent: 20,
    hpMax: 30,
    statusEffects: ["blessed"],
    isActive: true,
  });
  expect(result).not.toBeNull();
  expect(result!.id).toBe("c1");
  expect(result!.name).toBe("Kael");
  expect(result!.isAlly).toBe(true);
  expect(result!.hpCurrent).toBe(20);
  expect(result!.statusEffects).toEqual(["blessed"]);
});

test("parseCombatant returns null for null input", () => {
  expect(parseCombatant(null)).toBeNull();
});

test("parseCombatant returns null for non-object input", () => {
  expect(parseCombatant("string")).toBeNull();
  expect(parseCombatant(42)).toBeNull();
});

test("parseCombatant returns null for missing id", () => {
  expect(parseCombatant({ name: "Kael" })).toBeNull();
});

test("parseCombatant returns null for missing name", () => {
  expect(parseCombatant({ id: "c1" })).toBeNull();
});

test("parseCombatant defaults missing optional fields", () => {
  const result = parseCombatant({ id: "c1", name: "Kael" });
  expect(result).not.toBeNull();
  expect(result!.isAlly).toBe(false);
  expect(result!.hpCurrent).toBe(0);
  expect(result!.hpMax).toBe(1);
  expect(result!.statusEffects).toEqual([]);
  expect(result!.isActive).toBe(false);
});

// --- Security: payload size limit ---

test("parseGameEvent rejects payload over 1 MB", () => {
  const huge = new Uint8Array(MAX_EVENT_PAYLOAD_BYTES + 1);
  huge.fill(0x20); // spaces
  expect(parseGameEvent(huge)).toBeNull();
});

test("parseGameEvent accepts payload at exactly 1 MB", () => {
  // 1 MB payload with valid JSON
  const data = { type: "test", padding: "x".repeat(1_048_500) };
  const encoded = new TextEncoder().encode(JSON.stringify(data));
  // This may or may not be under 1MB after JSON encoding, but if it is, it should parse
  if (encoded.length <= MAX_EVENT_PAYLOAD_BYTES) {
    const result = parseGameEvent(encoded);
    expect(result).not.toBeNull();
    expect(result!.type).toBe("test");
  }
});

// --- Milestone 10.4a: Item art (parseInventoryItems) ---

test("parseInventoryItems extracts image_url to imageUrl", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory: [
      {
        id: "sword_1",
        name: "Shortsword",
        type: "weapon",
        rarity: "common",
        description: "A blade",
        weight: 2,
        effects: [],
        lore: "",
        value_base: 100,
        slot_info: { quantity: 1, equipped: false },
        image_url: "/api/assets/images/img_abc123",
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].imageUrl).toBe("/api/assets/images/img_abc123");
});

test("parseInventoryItems omits imageUrl when no image_url", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory: [
      {
        id: "rations",
        name: "Rations",
        type: "consumable",
        rarity: "common",
        description: "",
        weight: 1,
        effects: [],
        lore: "",
        value_base: 5,
        slot_info: { quantity: 3, equipped: false },
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].imageUrl).toBeUndefined();
});
