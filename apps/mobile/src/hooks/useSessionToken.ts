import { useCallback, useState } from "react";
import { API_BASE, authHeaders } from "@/utils/api";

export type TokenState = "idle" | "fetching" | "ready" | "error";

const ALLOWED_LK_PROTOCOL = __DEV__ ? /^wss?:\/\// : /^wss:\/\//;

interface TokenResponse {
  token: string;
  url: string;
  room_name: string;
}

export function useSessionToken() {
  const [state, setState] = useState<TokenState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | undefined>(undefined);
  const [serverUrl, setServerUrl] = useState<string | undefined>(undefined);

  const fetchToken = useCallback(async (roomName: string) => {
    setState("fetching");
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/api/livekit/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ room_name: roomName }),
      });

      if (!res.ok) {
        const err = (await res.json()) as { error?: string };
        throw new Error(err.error ?? "Failed to get token");
      }

      const data = (await res.json()) as TokenResponse;
      if (!ALLOWED_LK_PROTOCOL.test(data.url)) {
        throw new Error("Server returned an invalid URL protocol");
      }
      setToken(data.token);
      setServerUrl(data.url);
      setState("ready");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Connection failed";
      setError(msg);
      setState("error");
    }
  }, []);

  const reset = useCallback(() => {
    setToken(undefined);
    setServerUrl(undefined);
    setState("idle");
  }, []);

  return { state, error, token, serverUrl, fetchToken, reset };
}
