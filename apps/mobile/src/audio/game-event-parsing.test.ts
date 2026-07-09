import { test, expect } from "bun:test";
import {
  parseGameEvent,
  parseCombatant,
  parseInventoryItems,
  parseRarity,
  MAX_EVENT_PAYLOAD_BYTES,
} from "./game-event-parsing";

function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

// --- parseGameEvent ---

test("parseGameEvent rejects an oversize payload", () => {
  const oversized = new Uint8Array(MAX_EVENT_PAYLOAD_BYTES + 1);
  expect(parseGameEvent(oversized)).toBeNull();
});

test("parseGameEvent rejects a payload missing the type field", () => {
  expect(parseGameEvent(encode({ foo: "bar" }))).toBeNull();
});

test("parseGameEvent parses a valid payload", () => {
  const event = parseGameEvent(encode({ type: "dice_roll", roll: 15 }));
  expect(event).not.toBeNull();
  expect(event!.type).toBe("dice_roll");
  expect(event!.roll).toBe(15);
});

// --- parseCombatant ---

test("parseCombatant rejects null and malformed input", () => {
  expect(parseCombatant(null)).toBeNull();
  expect(parseCombatant({ id: "c1" })).toBeNull(); // missing name
  expect(parseCombatant("not an object")).toBeNull();
});

test("parseCombatant fills fail-soft defaults for missing optional fields", () => {
  const combatant = parseCombatant({ id: "c1", name: "Goblin" });
  expect(combatant).not.toBeNull();
  expect(combatant!.id).toBe("c1");
  expect(combatant!.name).toBe("Goblin");
  expect(combatant!.isAlly).toBe(false);
  expect(combatant!.hpCurrent).toBe(0);
  expect(combatant!.hpMax).toBe(1);
  expect(combatant!.conditions).toEqual([]);
  expect(combatant!.isActive).toBe(false);
});

// --- parseInventoryItems / parseRarity ---

test("parseInventoryItems shapes raw items with defaults", () => {
  const items = parseInventoryItems([
    {
      id: "i1",
      name: "Sword",
      type: "weapon",
      rarity: "rare",
      slot_info: { quantity: 2, equipped: true },
    },
  ]);
  expect(items).toHaveLength(1);
  expect(items[0].id).toBe("i1");
  expect(items[0].rarity).toBe("rare");
  expect(items[0].quantity).toBe(2);
  expect(items[0].equipped).toBe(true);
});

test("parseRarity falls back to common for unknown values", () => {
  expect(parseRarity("legendary")).toBe("legendary");
  expect(parseRarity("mythic")).toBe("common");
  expect(parseRarity(undefined)).toBe("common");
});
