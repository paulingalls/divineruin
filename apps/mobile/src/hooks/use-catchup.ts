import { useEffect, useRef } from "react";
import { AppState } from "react-native";
import { catchupStore, type CatchUpCard } from "@/stores/catchup-store";
import { API_BASE, authHeaders } from "@/utils/api";

const POLL_INTERVAL_MS = 60_000;

export async function fetchCards(): Promise<void> {
  const store = catchupStore.getState();
  store.setLoading(store.lastFetchedAt === null);
  try {
    const res = await fetch(`${API_BASE}/api/catchup`, {
      headers: authHeaders(),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      throw new Error(body.error ?? `HTTP ${res.status}`);
    }
    const data = (await res.json()) as { items: CatchUpCard[] };
    store.setFetched(data.items);
  } catch (err) {
    store.setError(err instanceof Error ? err.message : "Failed to load");
  }
}

export function useCatchUp(enabled = true) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    void fetchCards();

    const startPolling = () => {
      if (intervalRef.current) return;
      intervalRef.current = setInterval(() => {
        void fetchCards();
      }, POLL_INTERVAL_MS);
    };

    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    startPolling();

    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        void fetchCards();
        startPolling();
      } else {
        stopPolling();
      }
    });

    return () => {
      stopPolling();
      subscription.remove();
    };
  }, [enabled]);
}
