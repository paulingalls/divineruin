import { useState, useCallback, useEffect } from "react";
import { authStore } from "@/stores/auth-store";
import { catchupStore } from "@/stores/catchup-store";
import { API_BASE } from "@/utils/api";
import { fetchCards } from "@/hooks/use-catchup";
import { playSfx } from "@/audio/sfx-player";
import { hapticSuccess } from "@/audio/haptics";
import {
  applyMutationInventory,
  inventoryRequestContext,
  isInventoryRequestCurrent,
} from "@/audio/inventory-refresh";

export function useActivityActions() {
  const [decisionLoading, setDecisionLoading] = useState(false);
  useEffect(
    () =>
      authStore.subscribe((state, previous) => {
        if (
          state.playerId !== previous.playerId ||
          state.token !== previous.token ||
          state.phase !== previous.phase
        )
          setDecisionLoading(false);
      }),
    [],
  );

  const submitDecision = useCallback(async (activityId: string, decisionId: string) => {
    const context = inventoryRequestContext();
    setDecisionLoading(true);
    const previousCards = catchupStore.getState().cards;
    catchupStore.getState().removeCard(activityId);
    try {
      const res = await fetch(`${API_BASE}/api/activities/${activityId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${context.token}` },
        body: JSON.stringify({ decision_id: decisionId }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body: unknown = await res.json();
      if (!isInventoryRequestCurrent(context)) return;
      applyMutationInventory(body, context);
      playSfx("success_sting");
      hapticSuccess();
    } catch {
      if (isInventoryRequestCurrent(context)) {
        catchupStore.getState().setCards(previousCards);
        playSfx("fail_sting");
      }
    } finally {
      if (isInventoryRequestCurrent(context)) setDecisionLoading(false);
    }
  }, []);

  const startActivity = useCallback(async (type: string, parameters: Record<string, unknown>) => {
    const context = inventoryRequestContext();
    const res = await fetch(`${API_BASE}/api/activities`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${context.token}` },
      body: JSON.stringify({ type, parameters }),
    });
    if (!isInventoryRequestCurrent(context)) return;
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      throw new Error(body.error ?? `HTTP ${res.status}`);
    }
    const body: unknown = await res.json();
    if (!isInventoryRequestCurrent(context)) return;
    applyMutationInventory(body, context, type === "crafting");
    await fetchCards().catch(() => {});
  }, []);

  return { submitDecision, startActivity, decisionLoading };
}
