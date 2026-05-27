import { test, expect } from "bun:test";
import { armReveal, REVEAL_ARMED_CLASS, REVEAL_ITEM_CLASS } from "./useReveal.ts";
import { REVEALED_CLASS, type RevealEnv } from "./reveal.ts";

// apps/web tests run on bare `bun test` — no happy-dom/jsdom, so there is no
// global IntersectionObserver, matchMedia, or DOM. armReveal is the pure,
// DOM-injectable core of useReveal (mirrors reveal.ts's RevealEnv seam): tests
// pass a fake section + a stub env so every branch runs without a real DOM. The
// React wrapper (useReveal's useEffect/useRef) is a thin binding whose live
// scroll behavior is covered by web-world.e2e.ts + web-above-fold.e2e.ts.

// Minimal Element stand-in: only the classList surface reveal() touches.
function fakeItem() {
  const classes = new Set<string>();
  return {
    classList: {
      add: (c: string) => classes.add(c),
      contains: (c: string) => classes.has(c),
    },
  } as unknown as Element;
}

// Minimal section stand-in: records the armed class and the selector passed to
// querySelectorAll, and hands back the items the test seeded.
function fakeSection(items: Element[]) {
  const added: string[] = [];
  const selectors: string[] = [];
  const section = {
    classList: { add: (c: string) => void added.push(c) },
    querySelectorAll: (s: string) => {
      selectors.push(s);
      return items as unknown as NodeListOf<Element>;
    },
  };
  return { section, added, selectors };
}

// IntersectionObserver stub recording lifecycle calls (same shape as reveal.test.ts).
function fakeObserverFactory() {
  const calls = { observed: [] as Element[], disconnected: 0 };
  const instance: Pick<IntersectionObserver, "observe" | "unobserve" | "disconnect"> = {
    observe: (el: Element) => void calls.observed.push(el),
    unobserve: () => {},
    disconnect: () => void (calls.disconnected += 1),
  };
  const ctor = function () {
    return instance;
  } as unknown as typeof IntersectionObserver;
  return { ctor, calls };
}

test("arms the section and observes each reveal-item, cleanup disconnects", () => {
  const { ctor, calls } = fakeObserverFactory();
  const items = [fakeItem(), fakeItem(), fakeItem()];
  const { section, added, selectors } = fakeSection(items);
  const env: RevealEnv = { IntersectionObserver: ctor, prefersReducedMotion: false };

  const cleanup = armReveal(section, env);

  expect(added).toEqual([REVEAL_ARMED_CLASS]);
  expect(selectors).toEqual([`.${REVEAL_ITEM_CLASS}`]);
  expect(calls.observed).toEqual(items);

  cleanup();
  expect(calls.disconnected).toBe(1);
});

test("reduced motion arms the section and reveals every item, no observer", () => {
  let constructed = 0;
  const spyCtor = function () {
    constructed += 1;
    return { observe() {}, unobserve() {}, disconnect() {} };
  } as unknown as typeof IntersectionObserver;
  const items = [fakeItem(), fakeItem()];
  const { section, added } = fakeSection(items);
  const env: RevealEnv = { IntersectionObserver: spyCtor, prefersReducedMotion: true };

  const cleanup = armReveal(section, env);

  expect(added).toEqual([REVEAL_ARMED_CLASS]);
  for (const it of items) expect(it.classList.contains(REVEALED_CLASS)).toBe(true);
  expect(constructed).toBe(0);
  expect(() => cleanup()).not.toThrow();
});

test("no IntersectionObserver (SSR): no arm, no query, safe no-op", () => {
  const items = [fakeItem()];
  const { section, added, selectors } = fakeSection(items);
  const env: RevealEnv = { IntersectionObserver: undefined, prefersReducedMotion: false };

  let cleanup: () => void = () => {};
  expect(() => {
    cleanup = armReveal(section, env);
  }).not.toThrow();

  expect(added).toEqual([]);
  expect(selectors).toEqual([]);
  expect(items[0]!.classList.contains(REVEALED_CLASS)).toBe(false);
  expect(() => cleanup()).not.toThrow();
});

test("null section is a safe no-op", () => {
  const env: RevealEnv = { IntersectionObserver: undefined, prefersReducedMotion: false };
  let cleanup: () => void = () => {};
  expect(() => {
    cleanup = armReveal(null, env);
  }).not.toThrow();
  expect(() => cleanup()).not.toThrow();
});

test("shared class constants match the literals reveal-gate.css keys off", () => {
  // Guards the CSS<->hook coupling, like reveal.test.ts guards REVEALED_CLASS:
  // reveal-gate.css hides `.reveal-armed .reveal-item` and reveals `.is-revealed`.
  expect(REVEAL_ARMED_CLASS).toBe("reveal-armed");
  expect(REVEAL_ITEM_CLASS).toBe("reveal-item");
});
