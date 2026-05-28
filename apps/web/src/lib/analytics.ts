// Privacy-aware, hydration-safe, non-render-blocking analytics for the marketing site. No
// third-party script, no cookies, no PII — just event names + minimal string/number props. Two
// transports run per event: an in-page CustomEvent("dr:analytics") seam (decouples event production
// from delivery, and is the hook the web-conversion e2e observes), and — only when
// PUBLIC_ANALYTICS_URL is configured at deploy — a fire-and-forget navigator.sendBeacon to that
// first-party endpoint. Everything is browser-only: imported during prerender (no window) it is
// side-effect-free and dispatches nothing. Injectable transport seam mirrors api.ts's JoinOpts.

export interface AnalyticsPayload {
  name: string;
  props?: Record<string, string | number>;
  ts: number;
}

type Transport = (payload: AnalyticsPayload) => void;

// Default delivery: in-page event always, first-party beacon when configured. SSR/no-window or a
// runtime without sendBeacon → no-op (never throws), so prerender and old browsers stay safe.
function defaultTransport(payload: AnalyticsPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("dr:analytics", { detail: payload }));
  const url = typeof process !== "undefined" ? process.env.PUBLIC_ANALYTICS_URL : undefined;
  if (
    url &&
    url.length > 0 &&
    typeof navigator !== "undefined" &&
    typeof navigator.sendBeacon === "function"
  ) {
    navigator.sendBeacon(url, JSON.stringify(payload));
  }
}

// Track one event. `transport` is injectable so tests deliver to a fake sink without a browser.
export function trackEvent(
  name: string,
  props?: Record<string, string | number>,
  transport: Transport = defaultTransport,
): void {
  transport({ name, props, ts: Date.now() });
}

let inited = false;

// Call once from the browser hydration entry (client.tsx). No-op during prerender (no window) and
// on any repeat call. Tracks the initial page_view and installs ONE delegated click listener that
// tracks cta_click for the site's #waitlist CTAs (Hero + NavBar share that href), so those
// components need no analytics wiring of their own.
export function initAnalytics(transport: Transport = defaultTransport): void {
  if (typeof window === "undefined" || inited) return;
  inited = true;
  trackEvent("page_view", { path: location.pathname }, transport);
  document.addEventListener("click", (e) => {
    const target = e.target as Element | null;
    if (target?.closest('a[href="#waitlist"]')) {
      trackEvent("cta_click", { href: "#waitlist" }, transport);
    }
  });
}

// Test-only: clears the module-level init guard so each test starts fresh.
export function __resetForTest(): void {
  inited = false;
}
