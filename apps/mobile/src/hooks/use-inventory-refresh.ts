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

export function useInventoryRefresh() {
  useEffect(() => {
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
      try {
        const res = await fetch(`${API_BASE}/api/inventory`, {
          headers: { Authorization: `Bearer ${context.token}` },
          signal: abort.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const snapshot = parseHttpInventory(await res.json(), context.playerId!);
        if (!current()) return;
        if (panelStore.getState().inventoryGeneration !== context.generation) {
          fresh = true;
          return;
        }
        applyInventorySnapshot(snapshot, context.playerId!);
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
  }, []);
}
