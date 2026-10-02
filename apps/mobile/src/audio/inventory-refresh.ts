import { authStore } from "@/stores/auth-store";
import { characterStore } from "@/stores/character-store";
import { panelStore } from "@/stores/panel-store";
import { parseInventoryItems, type DataChannelEvent } from "./game-event-parsing";

export function applyInventorySnapshot(
  event: DataChannelEvent,
  localPlayerId = authStore.getState().playerId ?? characterStore.getState().character?.playerId,
  store: typeof panelStore = panelStore,
): void {
  if (!Array.isArray(event.inventory) && event.type !== "inventory_updated") return;
  const state = store.getState();
  if (event.player_id === undefined) {
    if (authStore.getState().phase === "authenticated" || state.inventoryRevision !== null) return;
    if (Array.isArray(event.inventory))
      state.setInventory(parseInventoryItems(event.inventory as Record<string, unknown>[]));
    return;
  }
  if (event.player_id !== localPlayerId) return;
  const snapshot = parseHttpInventory(event, localPlayerId);
  state.acceptInventory(
    localPlayerId,
    snapshot.inventory_revision as string,
    parseInventoryItems(snapshot.inventory as Record<string, unknown>[]),
  );
}

let authGeneration = 0;
authStore.subscribe((state, previous) => {
  if (
    state.playerId !== previous.playerId ||
    state.token !== previous.token ||
    state.phase !== previous.phase
  )
    authGeneration++;
});

export function inventoryRequestContext() {
  const { playerId, token } = authStore.getState();
  return { playerId, token, authGeneration, generation: panelStore.getState().inventoryGeneration };
}

export function isInventoryRequestCurrent(
  context: ReturnType<typeof inventoryRequestContext>,
): boolean {
  return context.authGeneration === authGeneration;
}

export function parseHttpInventory(value: unknown, playerId: string): DataChannelEvent {
  const data = value as DataChannelEvent | null;
  if (
    data?.player_id !== playerId ||
    !Array.isArray(data.inventory) ||
    typeof data.inventory_revision !== "string" ||
    !/^(0|[1-9][0-9]*)$/.test(data.inventory_revision)
  )
    throw new Error("Invalid inventory snapshot");
  for (const entry of data.inventory) {
    const item = entry as Record<string, unknown> | null;
    const slot = item?.slot_info as { quantity?: unknown } | undefined;
    const quantity = slot?.quantity;
    if (
      typeof item?.id !== "string" ||
      typeof item.name !== "string" ||
      !slot ||
      typeof slot !== "object" ||
      Array.isArray(slot) ||
      (quantity !== undefined && (typeof quantity !== "number" || quantity <= 0))
    )
      throw new Error("Invalid inventory item");
  }
  return data;
}

export function applyMutationInventory(
  value: unknown,
  context: ReturnType<typeof inventoryRequestContext>,
  required = false,
): void {
  if (!isInventoryRequestCurrent(context)) return;
  const data = value as Record<string, unknown>;
  if (!("inventory" in data)) {
    if (required) throw new Error("Missing committed inventory snapshot");
    return;
  }
  const snapshot = parseHttpInventory(data, context.playerId!);
  const before = panelStore.getState().inventoryGeneration;
  applyInventorySnapshot(snapshot, context.playerId!);
  if (before !== context.generation && panelStore.getState().inventoryGeneration === before)
    panelStore.getState().requestInventoryRefresh();
  panelStore.getState().setInventoryRefreshError(null);
}
