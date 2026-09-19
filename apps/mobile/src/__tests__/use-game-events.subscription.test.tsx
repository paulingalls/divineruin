import { expect, mock, test } from "bun:test";
import { useCallback, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { ReceivedDataMessage } from "@/livekit";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";
import { encode, resetStores, SAMPLE_CHARACTER } from "./use-game-events.helpers";

const handlers: ((message: ReceivedDataMessage) => void)[] = [];
await mock.module("@/livekit", () => ({
  useDataChannel: (_topic: string, onMessage: (message: ReceivedDataMessage) => void) => {
    handlers.push(onMessage);
    return { message: undefined, send: () => {}, isSending: false };
  },
}));

const { useGameEvents } = await import("@/hooks/use-game-events");

/** Renders twice: a render-phase update re-runs the component with its hooks intact. */
function Rerendering({ observe }: { observe?: (message: ReceivedDataMessage) => void }) {
  const [pass, setPass] = useState(0);
  const stable = useCallback(
    (message: ReceivedDataMessage) => observe?.(message),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  useGameEvents(observe ? stable : undefined);
  if (pass === 0) setPass(1);
  return null;
}

test("a re-render does not re-subscribe the game_events data channel", () => {
  handlers.length = 0;
  renderToStaticMarkup(<Rerendering />);
  expect(handlers).toHaveLength(2);
  expect(handlers[0]).toBe(handlers[1]);

  handlers.length = 0;
  renderToStaticMarkup(<Rerendering observe={() => {}} />);
  expect(handlers).toHaveLength(2);
  expect(handlers[0]).toBe(handlers[1]);
});

test("the observer sees every packet, including one the DM-sender check drops", () => {
  resetStores();
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handlers.length = 0;
  const seen: (boolean | undefined)[] = [];
  renderToStaticMarkup(<Rerendering observe={(message) => seen.push(message.from?.isAgent)} />);
  const packet = (isAgent: boolean) =>
    ({
      payload: encode({
        type: "location_changed",
        new_location: "accord_market_square",
        location_name: "Market Square",
      }),
      from: { isAgent },
    }) as never;

  handlers[0]?.(packet(false));
  expect(sessionStore.getState().locationContext).toBeNull();
  handlers[0]?.(packet(true));
  expect(sessionStore.getState().locationContext?.locationId).toBe("accord_market_square");
  expect(seen).toEqual([false, true]);
  resetStores();
});
