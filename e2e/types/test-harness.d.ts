/**
 * The `window.__DR` test bridge, declared once for the whole e2e suite.
 *
 * Mirrors `apps/mobile/src/types/test-harness.d.ts` — the producer-side
 * declaration that `apps/mobile/src/app/session-test.tsx` assigns against.
 * Kept as a hand-copy rather than an import, following the same rule
 * `fixtures/session.ts` already states for `GameEvent`: no cross-project
 * imports from e2e into the app.
 *
 * That copy is deliberate but not free — the producer types `openPanel` as
 * `(tab: PanelTab)` and the event as `DataChannelEvent`, both narrower than
 * what we can express here without importing them. Declaring once removes the
 * duplication inside e2e; it does not bind us to the producer's contract, so
 * these two files can still drift apart silently.
 */
import type { GameEvent } from "../fixtures/session.js";

declare global {
  interface Window {
    __DR?: {
      handleGameEvent: (event: GameEvent) => void;
      openPanel: (tab: string) => void;
      closePanel: () => void;
    };
  }
}
