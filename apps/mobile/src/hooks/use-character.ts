import { useEffect, useState } from "react";
import { API_BASE, authHeaders } from "@/utils/api";
import { characterStore } from "@/stores/character-store";

interface CharacterResponse {
  player_id: string;
  name: string;
  race?: string;
  class: string;
  level: number;
  xp: number;
  location_id: string;
  location_name: string;
  hp_current: number;
  hp_max: number;
  deity?: string;
  portrait_url?: string;
}

export function useCharacter(playerId: string) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchCharacter() {
      try {
        const res = await fetch(`${API_BASE}/api/character/${playerId}`, {
          headers: authHeaders(),
        });
        if (res.status === 404) {
          // Player exists but character not yet created — not an error
          if (!cancelled) {
            characterStore.getState().clear();
            setError(null);
          }
          return;
        }
        if (!res.ok) {
          throw new Error(`Failed to fetch character (${res.status})`);
        }
        const data = (await res.json()) as CharacterResponse;
        if (cancelled) return;
        characterStore.getState().setCharacter({
          playerId: data.player_id,
          name: data.name,
          race: typeof data.race === "string" ? data.race : "",
          className: data.class,
          level: data.level,
          xp: data.xp,
          locationId: data.location_id,
          locationName: data.location_name,
          hpCurrent: data.hp_current,
          hpMax: data.hp_max,
          deity: typeof data.deity === "string" ? data.deity : "",
          portraitUrl: typeof data.portrait_url === "string" ? data.portrait_url : null,
        });
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Failed to load character";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void fetchCharacter();
    return () => {
      cancelled = true;
    };
  }, [playerId]);

  return { loading, error };
}
