import { useEffect, useRef, type RefObject } from "react";
import { reveal, defaultRevealEnv, type RevealEnv } from "./reveal.ts";
import "./reveal-gate.css";

// JS-only marker the hook adds to the section AFTER hydration (never in the
// prerendered HTML); reveal-gate.css keys the pre-reveal hidden state off it, so
// with no JS / SSR / reduced motion the content stays fully visible — arming is
// pure progressive enhancement.
export const REVEAL_ARMED_CLASS = "reveal-armed";

// Shared class on every scroll-revealed element. reveal-gate.css's single rule
// targets `.reveal-armed .reveal-item`, so sections opt an element into the
// reveal animation by adding this class — no per-section gate CSS.
export const REVEAL_ITEM_CLASS = "reveal-item";

const noop = (): void => {};

// The slice of a section element armReveal touches. Narrower than HTMLElement so
// the no-DOM tests can pass a plain stub (an HTMLElement ref still satisfies it).
export interface RevealSection {
  classList: { add(token: string): void };
  querySelectorAll(selectors: string): Iterable<Element>;
}

// Pure, DOM-injectable core (mirrors reveal.ts's RevealEnv seam so it unit-tests
// under bare `bun test`): arm the section, then hand its reveal-items to
// reveal(). Returns a cleanup that tears the observer down. The IntersectionObserver
// guard runs before arming so SSR/prerender leaves the section untouched —
// matching the per-section useEffect this replaces.
export function armReveal(section: RevealSection | null, env: RevealEnv): () => void {
  if (!section || !env.IntersectionObserver) return noop;
  section.classList.add(REVEAL_ARMED_CLASS);
  return reveal(section.querySelectorAll(`.${REVEAL_ITEM_CLASS}`), env);
}

// Post-hydration scroll-reveal for a section. Returns a ref to attach to the
// section element. Call it at the top of a section component and spread
// `reveal-item` onto each element that should reveal on scroll:
//
//   const sectionRef = useReveal<HTMLElement>();
//   return <section className="premise" ref={sectionRef}>...
//     <li className="premise__item reveal-item">...
//
// Returning armReveal's cleanup directly means React StrictMode's double-invoke
// disconnects the first observer before the second is created — no leak.
export function useReveal<T extends HTMLElement = HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T>(null);
  useEffect(() => armReveal(ref.current, defaultRevealEnv()), []);
  return ref;
}
