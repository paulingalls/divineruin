import { useEffect, useState } from "react";
import { API_BASE } from "@/utils/api";
import { characterStore } from "@/stores/character-store";

export function useCharacter(playerId: string) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchCharacter() {
      try {
        const res = await fetch(`${API_BASE}/api/character/${playerId}`);
        if (!res.ok) {
          throw new Error(`Failed to fetch character (${res.status})`);
        }
        const data = await res.json();
        if (cancelled) return;
        characterStore.getState().setCharacter({
          playerId: data.player_id,
          name: data.name,
          level: data.level,
          xp: data.xp,
          locationId: data.location_id,
          locationName: data.location_name,
          hpCurrent: data.hp_current,
          hpMax: data.hp_max,
        });
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Failed to load character";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchCharacter();
    return () => {
      cancelled = true;
    };
  }, [playerId]);

  return { loading, error };
}
