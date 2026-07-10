import { useCallback, useState } from "react";
import { Share } from "react-native";

import { useMaybeRoomContext } from "@/livekit";
import { API_BASE, authHeaders } from "@/utils/api";
import { fetchInviteUrl } from "@/utils/invite-link";

export type InviteState = "idle" | "fetching" | "ready" | "error";

export function useInvite() {
  const room = useMaybeRoomContext();
  const [state, setState] = useState<InviteState>("idle");
  const [error, setError] = useState<string | null>(null);

  const share = useCallback(async () => {
    const roomName = room?.name;
    if (!roomName) {
      setError("Not connected to a room");
      setState("error");
      return;
    }

    setState("fetching");
    setError(null);

    try {
      const url = await fetchInviteUrl(roomName, API_BASE, authHeaders());
      await Share.share({ message: url });
      setState("ready");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create invite";
      setError(msg);
      setState("error");
    }
  }, [room]);

  return { state, error, share };
}
