import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Waitlist, WAITLIST_COPY } from "./Waitlist.tsx";

// No-DOM unit pattern (AudioDemo precedent for an interactive section): renderToStaticMarkup checks
// the default (idle) markup + form aria and proves hydration safety. The submit flow (type email ->
// POST /api/waitlist -> success/error swap) needs a live DOM + server and is covered by the
// web-conversion E2E (story-006); the joinWaitlist response mapping is unit-tested in api.test.ts.
// Reveal-free (matches AudioDemo): a form arming a scroll-reveal gate would be the wrong pattern.

// React escapes ' -> &#x27; in text; compare apostrophe copy against its escaped form.
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/'/g, "&#x27;");

test("renders the eyebrow, title, and lede at id=waitlist", () => {
  const html = renderToStaticMarkup(<Waitlist />);
  expect(html).toContain('id="waitlist"');
  expect(html).toContain("Enter the World");
  expect(html).toMatch(/The trial begins\s*<em>when the seal is broken\.<\/em>/);
  expect(html).toContain(esc("Closed playtest opens in waves through 2026."));
});

test("renders the email form in its idle state with accessible input", () => {
  const html = renderToStaticMarkup(<Waitlist />);
  expect(html).toContain("<form");
  expect(html).toContain('type="email"');
  expect(html).toContain("required");
  expect(html).toContain('aria-label="Email"');
  expect(html).toContain(`placeholder="${WAITLIST_COPY.placeholder}"`);
  expect(html).toContain(WAITLIST_COPY.submit);
});

test("renders the two meta lines", () => {
  const html = renderToStaticMarkup(<Waitlist />);
  expect(html).toContain(WAITLIST_COPY.metaCount);
  expect(html).toContain(WAITLIST_COPY.metaWave);
});

test("the idle render shows no success state (success is post-submit only)", () => {
  const html = renderToStaticMarkup(<Waitlist />);
  expect(html).not.toContain(WAITLIST_COPY.successLabel);
});

test("WAITLIST_COPY has non-empty fields", () => {
  for (const value of Object.values(WAITLIST_COPY)) {
    expect(typeof value).toBe("string");
    expect((value as string).length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Waitlist />)).not.toThrow();
});
