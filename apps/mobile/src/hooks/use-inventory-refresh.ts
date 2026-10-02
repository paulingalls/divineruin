import { useEffect } from "react";
import { AppState } from "react-native";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { API_BASE } from "@/utils/api";
import {
  applyInventorySnapshot,
  inventoryRequestContext,
  parseHttpInventory,
} from "@/audio/inventory-refresh";

let consumers = 0;
let stopRefresh: (() => void) | undefined;

function startRefresh() {
  let foreground = AppState.currentState === "active";
  let disposed = false;
  let epoch = 0;
  let eligible = false;
  let pending = false;
  let fresh = false;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;
  const canFetch = () => {
    const auth = authStore.getState();
    return (
      !disposed &&
      foreground &&
      panelStore.getState().isOpen &&
      auth.phase === "authenticated" &&
      !!auth.token &&
      !!auth.playerId
    );
  };
  const refresh = async () => {
    if (!canFetch() || pending) return;
    pending = true;
    fresh = false;
    const startEpoch = epoch;
    const context = inventoryRequestContext();
    const abort = new AbortController();
    controller = abort;
    const current = () => canFetch() && epoch === startEpoch;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    try {
      const snapshot = await Promise.race([
        (async () => {
          const res = await fetch(`${API_BASE}/api/inventory`, {
            headers: { Authorization: `Bearer ${context.token}` },
            signal: abort.signal,
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return parseHttpInventory(await res.json(), context.playerId!);
        })(),
        new Promise<never>((_, reject) => {
          deadline = setTimeout(() => {
            abort.abort();
            reject(new Error("Inventory request timed out"));
          }, 10000);
        }),
      ]);
      if (!current()) return;
      const before = panelStore.getState().inventoryGeneration;
      applyInventorySnapshot(snapshot, context.playerId!);
      if (before !== context.generation && panelStore.getState().inventoryGeneration === before)
        fresh = true;
      panelStore.getState().setInventoryRefreshError(null);
    } catch {
      if (current()) {
        if (panelStore.getState().inventoryGeneration !== context.generation) fresh = true;
        else
          panelStore
            .getState()
            .setInventoryRefreshError("Inventory refresh failed. Retrying in five seconds.");
      }
    } finally {
      if (deadline !== undefined) clearTimeout(deadline);
      pending = false;
      controller = undefined;
      if (fresh && canFetch()) void refresh();
    }
  };
  const reconcile = (invalidate = false) => {
    const next = canFetch();
    if (next === eligible && !invalidate) return;
    epoch++;
    controller?.abort();
    eligible = next;
    if (timer !== undefined) clearInterval(timer);
    timer = undefined;
    fresh = next;
    if (next) {
      timer = setInterval(() => {
        void refresh();
      }, 5000);
      void refresh();
    }
  };
  const unsubscribeAuth = authStore.subscribe((state, prev) => {
    if (
      state.playerId !== prev.playerId ||
      state.token !== prev.token ||
      state.phase !== prev.phase
    )
      reconcile(true);
  });
  const unsubscribePanel = panelStore.subscribe((state, prev) => {
    if (state.isOpen !== prev.isOpen) reconcile();
    if (state.inventoryRefreshRequest !== prev.inventoryRefreshRequest && canFetch()) {
      fresh = true;
      void refresh();
    }
  });
  const subscription = AppState.addEventListener("change", (state) => {
    foreground = state === "active";
    reconcile();
  });
  reconcile();
  return () => {
    disposed = true;
    epoch++;
    controller?.abort();
    if (timer !== undefined) clearInterval(timer);
    subscription.remove();
    unsubscribeAuth();
    unsubscribePanel();
  };
}

export function useInventoryRefresh() {
  useEffect(() => {
    consumers++;
    if (consumers === 1) stopRefresh = startRefresh();
    return () => {
      consumers--;
      if (consumers === 0) {
        stopRefresh?.();
        stopRefresh = undefined;
      }
    };
  }, []);
}
