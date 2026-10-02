import { Participant, ParticipantKind } from "livekit-client";
import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import {
  type DataChannelEvent,
  parseGameEvent,
  parseCombatant,
  MAX_EVENT_PAYLOAD_BYTES,
} from "@/audio/game-event-parsing";
import { panelStore, createPanelStore } from "@/stores/panel-store";
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
    conditions: [{ type: "blessed", stacks: 1, source: "cleric" }],
    isActive: true,
  });
  expect(result).not.toBeNull();
  expect(result!.id).toBe("c1");
  expect(result!.name).toBe("Kael");
  expect(result!.isAlly).toBe(true);
  expect(result!.hpCurrent).toBe(20);
  expect(result!.conditions).toEqual([{ type: "blessed", stacks: 1, source: "cleric" }]);
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
  expect(result!.conditions).toEqual([]);
  expect(result!.isActive).toBe(false);
});

test("parseCombatant drops malformed conditions and defaults stacks/source", () => {
  const result = parseCombatant({
    id: "c1",
    name: "Kael",
    conditions: [
      { type: "exhausted", stacks: 3, source: "march" },
      { type: "poisoned" }, // missing stacks/source -> defaulted
      { stacks: 2 }, // missing type -> dropped
      "not-an-object", // -> dropped
    ],
  });
  expect(result!.conditions).toEqual([
    { type: "exhausted", stacks: 3, source: "march" },
    { type: "poisoned", stacks: 1, source: "" },
  ]);
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

test("session_init preserves a material inventory row", () => {
  handleGameEvent({
    type: "session_init",
    inventory: [
      { id: "wolf_pelt", name: "Wolf Pelt", type: "material", slot_info: { quantity: 3 } },
    ],
  });
  const [material] = panelStore.getState().inventory;
  expect(material.name).toBe("Wolf Pelt");
  expect(material.type).toBe("material");
  expect(material.quantity).toBe(3);
});

test("inventory_updated preserves a material inventory row", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory_revision: "1",
    inventory: [
      { id: "wolf_pelt", name: "Wolf Pelt", type: "material", slot_info: { quantity: 2 } },
    ],
  });
  const [material] = panelStore.getState().inventory;
  expect(material.name).toBe("Wolf Pelt");
  expect(material.type).toBe("material");
  expect(material.quantity).toBe(2);
});

test("parseInventoryItems extracts image_url to imageUrl", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory_revision: "1",
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
    inventory_revision: "1",
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

type InventoryRow = Record<string, unknown> & {
  id: string;
  name: string;
  type: string;
  slot_info: { quantity: number };
};

type InventoryFixture = {
  owners: string[];
  initial_revisions: Record<string, string>;
  initial?: Record<string, InventoryRow[]>;
  sender?: { sid: string; identity: string; isAgent: boolean; kind: ParticipantKind };
  steps: {
    received: DataChannelEvent[];
    received_bytes?: number[][];
    expected: Record<string, InventoryRow[]>;
  }[];
};

test("committed inventory payloads reach independent consumers", async () => {
  const { applyInventorySnapshot } = await import("@/audio/inventory-refresh");
  const { parseInventoryItems } = await import("@/audio/game-event-parsing");
  const { handleGameEventMessage } = await import("@/audio/game-event-handler");
  const { authStore } = await import("@/stores/auth-store");
  const path = process.env.LIVE_MATERIAL_INVENTORY_FIXTURE;
  const fixture: InventoryFixture = path
    ? ((await Bun.file(path).json()) as InventoryFixture)
    : {
        owners: ["one", "two"],
        initial_revisions: { one: "0", two: "0" },
        steps: [
          {
            received: [
              {
                type: "inventory_updated",
                inventory_revision: "1",
                player_id: "one",
                inventory: [
                  {
                    id: "wolf_pelt",
                    name: "Wolf Pelt",
                    type: "material",
                    slot_info: { quantity: 2 },
                  },
                ],
              },
            ],
            expected: {
              one: [
                {
                  id: "wolf_pelt",
                  name: "Wolf Pelt",
                  type: "material",
                  slot_info: { quantity: 2 },
                },
              ],
              two: [],
            },
          },
        ],
      };
  expect(fixture.owners.length).toBeGreaterThan(1);
  expect(fixture.steps.length).toBeGreaterThan(0);
  if (path) {
    expect(fixture.sender?.isAgent).toBe(true);
    expect(Object.keys(fixture.initial ?? {}).sort()).toEqual([...fixture.owners].sort());
  }
  const consumers = [fixture.owners[0], fixture.owners[0], fixture.owners[1]].map((owner) => ({
    owner,
    store: createPanelStore(),
  }));
  for (const consumer of consumers) {
    consumer.store.getState().resetInventory(consumer.owner);
    consumer.store
      .getState()
      .acceptInventory(
        consumer.owner,
        fixture.initial_revisions[consumer.owner],
        parseInventoryItems(fixture.initial?.[consumer.owner] ?? []),
      );
  }
  let snapshots = 0;
  const previous: Record<string, Record<string, unknown>[]> = Object.fromEntries(
    fixture.owners.map((owner: string) => [owner, fixture.initial?.[owner] ?? []]),
  );
  const sender = new Participant(
    fixture.sender?.sid ?? "PA_unit_agent",
    fixture.sender?.identity ?? "unit-agent",
    undefined,
    undefined,
    undefined,
    undefined,
    fixture.sender?.kind ?? ParticipantKind.AGENT,
  );
  expect(sender.isAgent).toBe(true);
  for (const step of fixture.steps) {
    const decoded = (
      step.received_bytes ?? step.received.map((event) => Array.from(encode(event)))
    ).map((bytes) => {
      const event = parseGameEvent(new Uint8Array(bytes));
      expect(event).not.toBeNull();
      return event!;
    });
    if (path) {
      expect(step.received_bytes?.length).toBeGreaterThan(0);
      expect(decoded).toEqual(step.received);
    }
    for (const event of decoded) {
      expect(event.type).not.toBe("session_init");
      if (event.type === "inventory_updated") snapshots++;
      for (const consumer of consumers) {
        const before = consumer.store.getState().inventory;
        if (consumer.owner !== process.env.LIVE_MATERIAL_INVENTORY_IGNORE_CONSUMER) {
          applyInventorySnapshot(event, consumer.owner, consumer.store);
        }
        if (event.type === "inventory_updated" && event.player_id !== consumer.owner) {
          expect(consumer.store.getState().inventory).toEqual(before);
        }
      }
    }
    for (const consumer of consumers) {
      expect(
        consumer.store
          .getState()
          .inventory.map((item) => [item.id, item.name, item.type, item.quantity]),
      ).toEqual(
        step.expected[consumer.owner].map((item) => [
          item.id,
          item.name,
          item.type,
          item.slot_info.quantity,
        ]),
      );
      expect(consumer.store.getState().inventory).toEqual(
        parseInventoryItems(step.expected[consumer.owner]),
      );
    }
    for (const owner of fixture.owners) {
      authStore.setState({ playerId: owner });
      panelStore.getState().acceptInventory(owner, "0", parseInventoryItems(previous[owner]));
      for (const [index, event] of step.received.entries()) {
        const bytes = step.received_bytes?.[index];
        if (path && !bytes) throw new Error("Fixture omitted received game_events bytes");
        handleGameEventMessage({
          payload: bytes ? new Uint8Array(bytes) : encode(event),
          from: sender,
        });
      }
      expect(panelStore.getState().inventory).toEqual(parseInventoryItems(step.expected[owner]));
      previous[owner] = step.expected[owner];
      panelStore.getState().reset();
    }
  }
  expect(snapshots).toBeGreaterThan(0);
});
