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

  // Shared token request: host mint (/token, {room_name}) and guest redeem
  // (/redeem, {code}) differ only in path + body — everything else (auth
  // headers, !res.ok handling, protocol check, state transitions) is identical.
  const requestToken = useCallback(async (path: string, body: Record<string, unknown>) => {
    setState("fetching");
    setError(null);

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
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

  const fetchToken = useCallback(
    (roomName: string) => requestToken("/api/livekit/token", { room_name: roomName }),
    [requestToken],
  );

  // Guest join: exchange an invite code for a token scoped to the host's room.
  // Redeem never dispatches a DM server-side (M19 single-DM invariant).
  const redeemInvite = useCallback(
    (code: string) => requestToken("/api/livekit/redeem", { code }),
    [requestToken],
  );

  const reset = useCallback(() => {
    setToken(undefined);
    setServerUrl(undefined);
    setState("idle");
  }, []);

  return { state, error, token, serverUrl, fetchToken, redeemInvite, reset };
}
