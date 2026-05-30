import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Session, SESSION_LINES } from "./Session.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (NavBar/Hero/AudioDemo/Premise): renderToStaticMarkup proves the
// copy is in the prerendered HTML (SEO / visible without JS) and that render is
// hydration-safe. The scroll-reveal interaction (useReveal arms reveal-armed ->
// IntersectionObserver -> lines gain is-revealed) is DOM behavior, covered by the
// web-world / web-above-fold E2E.

const ALLOWED_VARIANTS = new Set(["", "player", "combat", "god"]);

test("renders the eyebrow, title, and lede", () => {
  const html = renderToStaticMarkup(<Session />);
  expect(html).toContain("A Session");
  expect(html).toMatch(/You speak\.\s*<em>The world speaks back\.<\/em>/);
  expect(html).toContain("Every word below is generated and voiced in real time");
});

test("renders every transcript line's speaker and words", () => {
  const html = renderToStaticMarkup(<Session />);
  for (const line of SESSION_LINES) {
    expect(html).toContain(line.who);
    expect(html).toContain(line.what);
  }
});

test("renders one transcript row per line", () => {
  const html = renderToStaticMarkup(<Session />);
  const rows = html.match(/class="session__line[^"]*"/g) ?? [];
  expect(rows.length).toBe(SESSION_LINES.length);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Session />);
  expect(html).not.toContain("reveal-armed");
});

test("REVEALED_CLASS matches the literal the reveal-gate CSS keys off", () => {
  // Guards the CSS<->helper coupling: reveal-gate.css hides un-revealed
  // .reveal-item lines and reveals .is-revealed ones; reveal() adds REVEALED_CLASS.
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("SESSION_LINES is the seven well-formed mockup lines", () => {
  expect(SESSION_LINES.length).toBe(7);
  for (const line of SESSION_LINES) {
    expect(line.who.length).toBeGreaterThan(0);
    expect(line.what.length).toBeGreaterThan(0);
    expect(ALLOWED_VARIANTS.has(line.variant)).toBe(true);
  }
});

test("includes the narrator, player, combat, and god voices", () => {
  // The section's point: many voices, one continuous scene.
  const variants = new Set(SESSION_LINES.map((l) => l.variant));
  expect(variants.has("")).toBe(true); // narrator (default)
  expect(variants.has("player")).toBe(true);
  expect(variants.has("combat")).toBe(true);
  expect(variants.has("god")).toBe(true);
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Session />)).not.toThrow();
});
