// Class the section components key their reveal CSS off. The pre-reveal hidden
// state is applied only under a JS-enabled root flag (owned by the section /
// capstone stories), so with no JS, reduced motion, or SSR the content stays
// fully visible — adding this class is the post-hydration progressive
// enhancement, never a requirement for the content to be seen.
export const REVEALED_CLASS = "is-revealed";

// Injectable environment seam. Production callers use the defaults; tests inject
// fakes because apps/web tests run on bare `bun test` with no DOM globals
// (no IntersectionObserver, no matchMedia).
export interface RevealEnv {
  IntersectionObserver?: typeof IntersectionObserver;
  prefersReducedMotion: boolean;
}

// Reads the live browser environment through typeof guards so the module imports
// cleanly during the build-time prerender (no window/IntersectionObserver there).
export function defaultRevealEnv(): RevealEnv {
  const hasIO = typeof IntersectionObserver !== "undefined";
  const prefersReducedMotion =
    typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  return {
    IntersectionObserver: hasIO ? IntersectionObserver : undefined,
    prefersReducedMotion,
  };
}

const noop = (): void => {};

// Reveal each target as it scrolls into view, then stop watching it (reveal
// once). Returns a cleanup that disconnects the observer.
//
// - No IntersectionObserver (SSR/prerender): safe no-op — targets are untouched.
// - prefers-reduced-motion: reveal every target immediately, create no observer.
// - Otherwise: one observer adds REVEALED_CLASS + unobserves on first intersect.
//
// Caller contract (sections in stories 002-004): call this inside a useEffect —
// never during render — exactly like NavBar attaches its scroll listener after
// hydration, and wire the returned cleanup to the effect's teardown:
//
//   useEffect(() => reveal(refs.current), []);
//
// Returning the cleanup directly means React StrictMode's double-invoke
// disconnects the first observer before the second is created — no leak.
export function reveal(
  targets: Iterable<Element>,
  env: RevealEnv = defaultRevealEnv(),
): () => void {
  if (!env.IntersectionObserver) return noop;

  const elements = [...targets];

  if (env.prefersReducedMotion) {
    for (const el of elements) el.classList.add(REVEALED_CLASS);
    return noop;
  }

  const observer = new env.IntersectionObserver((entries, obs) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add(REVEALED_CLASS);
      obs.unobserve(entry.target);
    }
  });
  for (const el of elements) observer.observe(el);
  return () => observer.disconnect();
}
