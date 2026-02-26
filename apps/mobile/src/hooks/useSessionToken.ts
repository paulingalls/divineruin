import { useCallback, useState } from "react";

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:3000";

export type TokenState = "idle" | "fetching" | "ready" | "error";

interface TokenResponse {
  token: string;
  url: string;
  room_name: string;
}

export function useSessionToken(playerId: string) {
  const [state, setState] = useState<TokenState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | undefined>(undefined);
  const [serverUrl, setServerUrl] = useState<string | undefined>(undefined);

  const fetchToken = useCallback(
    async (roomName: string) => {
      setState("fetching");
      setError(null);

      try {
        const res = await fetch(`${API_BASE}/api/livekit/token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: playerId, room_name: roomName }),
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error ?? "Failed to get token");
        }

        const data: TokenResponse = await res.json();
        setToken(data.token);
        setServerUrl(data.url);
        setState("ready");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Connection failed";
        setError(msg);
        setState("error");
      }
    },
    [playerId],
  );

  const reset = useCallback(() => {
    setToken(undefined);
    setServerUrl(undefined);
    setState("idle");
  }, []);

  return { state, error, token, serverUrl, fetchToken, reset };
}
