import { useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "zustand";
import { LEAVE_REQUESTED } from "@/audio/event-types";
import { sessionStore } from "@/stores/session-store";

export interface SessionTransport {
  isMicrophoneEnabled: boolean;
  setMicrophoneEnabled: (enabled: boolean) => Promise<unknown>;
  publishData: (
    payload: Uint8Array<ArrayBuffer>,
    options: { reliable: boolean; topic: string },
  ) => Promise<unknown>;
}

export function useLeaveRequest(transport: SessionTransport, exit: () => void) {
  const requested = useRef(false);
  const [wrappingUp, setWrappingUp] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const phase = useStore(sessionStore, (s) => s.phase);
  const clearDeadline = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => clearDeadline, [clearDeadline]);
  useEffect(() => {
    if (phase === "summary" || phase === "ended") clearDeadline();
  }, [phase, clearDeadline]);

  const requestLeave = useCallback(() => {
    if (requested.current) return;
    requested.current = true;
    setWrappingUp(true);
    sessionStore.getState().setPhase("ending");
    timer.current = setTimeout(() => {
      timer.current = null;
      if (sessionStore.getState().phase !== "summary") exit();
    }, 15000);
    const packet = new TextEncoder().encode(JSON.stringify({ type: LEAVE_REQUESTED }));
    void Promise.allSettled([
      Promise.resolve().then(() => transport.setMicrophoneEnabled(false)),
      Promise.resolve().then(() =>
        transport.publishData(packet, { reliable: true, topic: "player_hints" }),
      ),
    ]).then((results) => {
      for (const result of results) {
        if (result.status === "rejected")
          console.error("[session] Leave request failed:", result.reason);
      }
    });
  }, [transport, exit]);

  return { requestLeave, wrappingUp };
}
