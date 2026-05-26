import { test, expect } from "bun:test";
import { reveal, defaultRevealEnv, REVEALED_CLASS, type RevealEnv } from "./reveal.ts";

// apps/web tests run on bare `bun test` — no happy-dom/jsdom, so there is no
// global IntersectionObserver or matchMedia. reveal() takes its environment via
// an injectable seam (RevealEnv) so every branch is exercised here with plain
// stubs, exactly as NavBar.test.tsx unit-tests isScrolledPast without a DOM.

// Minimal Element stand-in: only the classList surface reveal() touches.
function fakeElement() {
  const classes = new Set<string>();
  return {
    classList: {
      add: (c: string) => classes.add(c),
      contains: (c: string) => classes.has(c),
    },
  } as unknown as Element;
}

// IntersectionObserver stub that records lifecycle calls and lets a test drive
// an element into view via trigger(). Captures the callback the constructor was
// handed so we can fire it on demand.
function fakeObserverFactory() {
  const calls = { observed: [] as Element[], unobserved: [] as Element[], disconnected: 0 };
  let captured: IntersectionObserverCallback | null = null;
  const instance: Pick<IntersectionObserver, "observe" | "unobserve" | "disconnect"> = {
    observe: (el: Element) => void calls.observed.push(el),
    unobserve: (el: Element) => void calls.unobserved.push(el),
    disconnect: () => void (calls.disconnected += 1),
  };
  const ctor = function (cb: IntersectionObserverCallback) {
    captured = cb;
    return instance;
  } as unknown as typeof IntersectionObserver;
  // Models the real IntersectionObserver contract: once an element is
  // unobserved it stops receiving entries, so re-triggering an unobserved
  // element is a no-op (mirrors the browser, where reveal-once relies on this).
  const trigger = (el: Element, isIntersecting = true) => {
    if (!captured) throw new Error("observer not constructed");
    if (calls.unobserved.includes(el)) return;
    captured(
      [{ isIntersecting, target: el } as IntersectionObserverEntry],
      instance as IntersectionObserver,
    );
  };
  return { ctor, calls, trigger };
}

test("reveals an element once when it enters view, then unobserves it", () => {
  const { ctor, calls, trigger } = fakeObserverFactory();
  const el = fakeElement();
  const env: RevealEnv = { IntersectionObserver: ctor, prefersReducedMotion: false };

  reveal([el], env);
  expect(calls.observed).toEqual([el]);
  expect(el.classList.contains(REVEALED_CLASS)).toBe(false);

  trigger(el);
  expect(el.classList.contains(REVEALED_CLASS)).toBe(true);
  expect(calls.unobserved).toEqual([el]);

  // Reveal-once: a second intersection must not re-process the element. This
  // guards the obs.unobserve() call — dropping it (e.g. a shared observer
  // refactor) would let the element be unobserved twice here.
  trigger(el);
  expect(calls.unobserved).toEqual([el]);
});

test("ignores entries that are not intersecting — no reveal, no unobserve", () => {
  const { ctor, calls, trigger } = fakeObserverFactory();
  const el = fakeElement();
  const env: RevealEnv = { IntersectionObserver: ctor, prefersReducedMotion: false };

  reveal([el], env);
  trigger(el, false);

  expect(el.classList.contains(REVEALED_CLASS)).toBe(false);
  expect(calls.unobserved).toEqual([]);
});

test("reduced motion reveals all targets immediately and creates no observer", () => {
  let constructed = 0;
  const spyCtor = function () {
    constructed += 1;
    return { observe() {}, unobserve() {}, disconnect() {} };
  } as unknown as typeof IntersectionObserver;
  const els = [fakeElement(), fakeElement()];
  const env: RevealEnv = { IntersectionObserver: spyCtor, prefersReducedMotion: true };

  const cleanup = reveal(els, env);

  for (const el of els) expect(el.classList.contains(REVEALED_CLASS)).toBe(true);
  expect(constructed).toBe(0);
  expect(() => cleanup()).not.toThrow();
});

test("is a safe no-op during SSR when IntersectionObserver is absent", () => {
  const el = fakeElement();
  const env: RevealEnv = { IntersectionObserver: undefined, prefersReducedMotion: false };

  let cleanup: () => void = () => {};
  expect(() => {
    cleanup = reveal([el], env);
  }).not.toThrow();

  expect(el.classList.contains(REVEALED_CLASS)).toBe(false);
  expect(() => cleanup()).not.toThrow();
});

test("defaultRevealEnv reads globals through guards without throwing in a no-DOM env", () => {
  const env = defaultRevealEnv();
  expect(env.IntersectionObserver).toBeUndefined();
  expect(env.prefersReducedMotion).toBe(false);
});
