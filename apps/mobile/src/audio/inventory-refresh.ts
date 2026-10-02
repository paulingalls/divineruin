import { authStore } from "@/stores/auth-store";
import { characterStore } from "@/stores/character-store";
import { panelStore, type InventoryItem } from "@/stores/panel-store";
import { parseInventoryItems, type DataChannelEvent } from "./game-event-parsing";

export function applyInventorySnapshot(
  event: DataChannelEvent,
  localPlayerId = authStore.getState().playerId ?? characterStore.getState().character?.playerId,
  setInventory: (items: InventoryItem[]) => void = panelStore.getState().setInventory,
): void {
  // Unscoped events are the legacy single-player contract.
  if (event.player_id !== undefined && event.player_id !== localPlayerId) return;
  if (Array.isArray(event.inventory)) {
    setInventory(parseInventoryItems(event.inventory as Record<string, unknown>[]));
  }
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
  if (data?.player_id !== playerId || !Array.isArray(data.inventory))
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
  if (panelStore.getState().inventoryGeneration !== context.generation) {
    panelStore.getState().requestInventoryRefresh();
    return;
  }
  applyInventorySnapshot(snapshot, context.playerId!);
  panelStore.getState().setInventoryRefreshError(null);
}
