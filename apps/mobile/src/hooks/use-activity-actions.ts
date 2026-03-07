import { useState, useCallback } from "react";
import { catchupStore } from "@/stores/catchup-store";
import { API_BASE, authHeaders } from "@/utils/api";
import { fetchCards } from "@/hooks/use-catchup";

export function useActivityActions() {
  const [decisionLoading, setDecisionLoading] = useState(false);

  const submitDecision = useCallback(async (activityId: string, decisionId: string) => {
    setDecisionLoading(true);

    // Optimistically remove the card
    const previousCards = catchupStore.getState().cards;
    catchupStore.getState().removeCard(activityId);

    try {
      const res = await fetch(`${API_BASE}/api/activities/${activityId}/decide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(),
        },
        body: JSON.stringify({ decision_id: decisionId }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
    } catch {
      // Restore on failure
      catchupStore.getState().setCards(previousCards);
    } finally {
      setDecisionLoading(false);
    }
  }, []);

  const startActivity = useCallback(async (type: string, parameters: Record<string, unknown>) => {
    const res = await fetch(`${API_BASE}/api/activities`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({ type, parameters }),
    });

    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      throw new Error(body.error ?? `HTTP ${res.status}`);
    }

    // Refresh the feed to show the new in-progress card
    await fetchCards().catch(() => {});
  }, []);

  return { submitDecision, startActivity, decisionLoading };
}
