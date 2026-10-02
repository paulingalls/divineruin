import { beforeEach, expect, test } from "bun:test";
import { Participant, ParticipantKind } from "livekit-client";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import {
  applyInventorySnapshot,
  parseHttpInventory,
  applyMutationInventory,
  inventoryRequestContext,
} from "@/audio/inventory-refresh";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { encode, resetStores } from "./use-game-events.helpers";
const agent = new Participant(
  "agent",
  "dm",
  undefined,
  undefined,
  undefined,
  undefined,
  ParticipantKind.AGENT,
);
const snapshot = (revision: string, quantity: number) => ({
  type: "inventory_updated",
  player_id: "owner",
  inventory_revision: revision,
  inventory: quantity ? [{ id: "oak_wood", name: "Oak Wood", slot_info: { quantity } }] : [],
});
beforeEach(() => {
  resetStores();
  authStore.setState({ playerId: "owner", token: "token", phase: "authenticated" });
});
test("delayed real agent snapshot cannot replace newer HTTP contents", () => {
  applyInventorySnapshot(parseHttpInventory(snapshot("9007199254740993", 3), "owner"));
  handleGameEventMessage({ payload: encode(snapshot("9007199254740992", 1)), from: agent });
  expect(panelStore.getState().inventory[0]?.quantity).toBe(3);
});
test("agent immediately advances revision, duplicate HTTP cannot resurrect empty inventory", () => {
  applyInventorySnapshot(snapshot("1", 1));
  handleGameEventMessage({ payload: encode(snapshot("2", 0)), from: agent });
  applyInventorySnapshot(snapshot("2", 3));
  expect(panelStore.getState().inventory).toEqual([]);
});
test("scoped revisions are mandatory canonical decimal strings", () => {
  for (const revision of [undefined, 1, "-1", "01", "1.1", "bad"]) {
    expect(() =>
      parseHttpInventory({ ...snapshot("1", 1), inventory_revision: revision }, "owner"),
    ).toThrow();
  }
});
test("adjacent revisions beyond number precision advance immediately", () => {
  applyInventorySnapshot(snapshot("9007199254740992", 1));
  handleGameEventMessage({ payload: encode(snapshot("9007199254740993", 3)), from: agent });
  expect(panelStore.getState().inventory[0]?.quantity).toBe(3);
  expect(panelStore.getState().inventoryRevision).toBe("9007199254740993");
});
test("auth transitions clear owner, revision and contents in one notification", () => {
  applyInventorySnapshot(snapshot("100", 3));
  const changes: object[] = [];
  const stop = panelStore.subscribe((state) =>
    changes.push({
      owner: state.inventoryOwner,
      revision: state.inventoryRevision,
      inventory: state.inventory,
    }),
  );
  authStore.setState({ playerId: "other" });
  stop();
  expect(changes).toEqual([{ owner: "other", revision: null, inventory: [] }]);
  handleGameEventMessage({ payload: encode(snapshot("101", 1)), from: agent });
  expect(panelStore.getState().inventory).toEqual([]);
  applyInventorySnapshot({ ...snapshot("1", 2), player_id: "other" });
  expect(panelStore.getState().inventory[0]?.quantity).toBe(2);
});
test("legacy packet and direct legacy setter cannot overwrite authenticated versioned cache", () => {
  applyInventorySnapshot(snapshot("1", 3));
  handleGameEventMessage({
    payload: encode({ type: "inventory_updated", inventory: [] }),
    from: agent,
  });
  panelStore.getState().setInventory([]);
  expect(panelStore.getState().inventory[0]?.quantity).toBe(3);
});
test("scoped session-init and agent messages fail on missing or malformed revisions", () => {
  for (const type of ["session_init", "inventory_updated"]) {
    for (const revision of [undefined, "bad"]) {
      expect(() =>
        handleGameEventMessage({
          payload: encode({ ...snapshot("1", 1), type, inventory_revision: revision }),
          from: agent,
        }),
      ).toThrow("Invalid inventory snapshot");
    }
  }
});

test("newer committed HTTP mutation advances after an intervening older agent update", () => {
  const context = inventoryRequestContext();
  handleGameEventMessage({ payload: encode(snapshot("1", 1)), from: agent });
  applyMutationInventory(snapshot("2", 3), context, true);
  expect(panelStore.getState().inventory[0]?.quantity).toBe(3);
  expect(panelStore.getState().inventoryRevision).toBe("2");
});

test("revision cache refuses direct snapshots for a different bound owner", () => {
  applyInventorySnapshot(snapshot("1", 3));
  panelStore.getState().acceptInventory("other", "2", []);
  expect(panelStore.getState().inventory[0]?.quantity).toBe(3);
  expect(panelStore.getState().inventoryOwner).toBe("owner");
});

test("legacy packet cannot populate an authenticated cache after HUD reset", () => {
  panelStore.getState().reset();
  handleGameEventMessage({
    payload: encode({ type: "inventory_updated", inventory: snapshot("1", 3).inventory }),
    from: agent,
  });
  expect(panelStore.getState().inventory).toEqual([]);
  expect(panelStore.getState().inventoryRevision).toBeNull();
});
