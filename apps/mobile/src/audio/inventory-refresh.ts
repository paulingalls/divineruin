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
