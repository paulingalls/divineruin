import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import {
  World,
  WORLD_TIMELINE,
  WORLD_PLACES,
  HOLLOW_TIERS,
  WORLD_META,
  placeStatusVariant,
} from "./World.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (Premise/Session): renderToStaticMarkup proves the copy is in the
// prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction and responsiveness are DOM behavior, covered by the
// story-006 capstone E2E.

test("renders the eyebrow, title, and lede", () => {
  const html = renderToStaticMarkup(<World />);
  expect(html).toContain("The World");
  expect(html).toMatch(/Aethos,\s*<em>and the wound at its center\.<\/em>/);
  expect(html).toContain("Ten gods tend a fantasy world that is running out of time");
});

test('renders id="world" — the anchor the capstone re-points Hero\'s CTA to', () => {
  // Locks the e72ce233ee75 contract here rather than as a broken capstone E2E.
  const html = renderToStaticMarkup(<World />);
  expect(html).toMatch(/<section[^>]*\sid="world"/);
});

test("renders the hollow-alert and the atmospheric quote pull", () => {
  const html = renderToStaticMarkup(<World />);
  expect(html).toContain("Hollow corruption detected");
  expect(html).toContain("The Hollow listens for names");
});

test("renders every timeline event's year and title", () => {
  const html = renderToStaticMarkup(<World />);
  for (const ev of WORLD_TIMELINE) {
    expect(html).toContain(ev.year);
    expect(html).toContain(ev.title);
  }
});

test("renders every place's name, kind, and status", () => {
  const html = renderToStaticMarkup(<World />);
  for (const p of WORLD_PLACES) {
    expect(html).toContain(p.name);
    expect(html).toContain(p.kind);
    expect(html).toContain(p.status);
  }
});

test("renders every Hollow tier's tier label and name", () => {
  const html = renderToStaticMarkup(<World />);
  for (const t of HOLLOW_TIERS) {
    expect(html).toContain(t.tier);
    expect(html).toContain(t.name);
  }
});

test("renders every meta entry's term and value", () => {
  const html = renderToStaticMarkup(<World />);
  for (const m of WORLD_META) {
    expect(html).toContain(m.term);
    expect(html).toContain(m.value);
  }
});

test("renders one card per item (timeline 5, places 6, tiers 4)", () => {
  const html = renderToStaticMarkup(<World />);
  const tlEvents = html.match(/class="world__tl-event[^"]*"/g) ?? [];
  const places = html.match(/class="world__place reveal-item"/g) ?? [];
  // Each tier <li> carries a unique world__tx--N modifier; matching the bare
  // world__tx prefix would also catch world__tx-meta/-name/-desc/-quote inner nodes.
  const tiers = html.match(/world__tx--\d/g) ?? [];
  expect(tlEvents.length).toBe(WORLD_TIMELINE.length);
  expect(tlEvents.length).toBe(5);
  expect(places.length).toBe(WORLD_PLACES.length);
  expect(places.length).toBe(6);
  expect(tiers.length).toBe(HOLLOW_TIERS.length);
  expect(tiers.length).toBe(4);
});

test("the 'Now' timeline event carries the --now modifier", () => {
  const html = renderToStaticMarkup(<World />);
  expect(html).toContain("world__tl-event--now");
  expect(WORLD_TIMELINE.filter((e) => e.now).length).toBe(1);
});

test("the redacted Hollow tier renders the crossed-out passage", () => {
  const html = renderToStaticMarkup(<World />);
  expect(html).toContain("[ this passage has been crossed out ]");
  expect(HOLLOW_TIERS.filter((t) => t.redacted).length).toBe(1);
});

test("placeStatusVariant maps every actual mockup status to its variant", () => {
  // All six statuses that appear in WORLD_PLACES — not just the enumerated set —
  // so an unmapped status fails loud here (assumption 6399e1e9681a).
  expect(placeStatusVariant("Held")).toBe("held");
  expect(placeStatusVariant("Lost")).toBe("lost");
  expect(placeStatusVariant("Bending")).toBe("warn");
  expect(placeStatusVariant("Held, barely")).toBe("warn");
  expect(placeStatusVariant("Contested")).toBe("warn");
  // Every status present in the data resolves to a known variant.
  for (const p of WORLD_PLACES) {
    expect(["held", "lost", "warn"]).toContain(placeStatusVariant(p.status));
  }
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<World />);
  expect(html).not.toContain("reveal-armed");
});

test("REVEALED_CLASS matches the literal the reveal-gate CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("content constants are the well-formed mockup sets", () => {
  expect(WORLD_TIMELINE.length).toBe(5);
  expect(WORLD_PLACES.length).toBe(6);
  expect(HOLLOW_TIERS.length).toBe(4);
  expect(WORLD_META.length).toBe(3);
  for (const ev of WORLD_TIMELINE) {
    expect(ev.year.length).toBeGreaterThan(0);
    expect(ev.title.length).toBeGreaterThan(0);
    expect(ev.desc.length).toBeGreaterThan(0);
  }
  for (const t of HOLLOW_TIERS) {
    expect(t.tier.length).toBeGreaterThan(0);
    expect(t.name.length).toBeGreaterThan(0);
    expect(t.quote.length).toBeGreaterThan(0);
  }
});

test("the redacted Tier-IV quote is decorative (aria-hidden)", () => {
  // The "[ crossed out ]" redacted quote is atmospheric, intentionally
  // unreadable (faint slate) — mark it aria-hidden so it's neither announced
  // nor flagged for color-contrast as meaningful text.
  const html = renderToStaticMarkup(<World />);
  expect(html).toMatch(
    /<p[^>]*class="world__tx-quote world__tx-quote--redacted"[^>]*aria-hidden="true"/,
  );
});

test("non-redacted tier quotes stay readable (no aria-hidden)", () => {
  // aria-hidden is gated on t.redacted only — the legible Tier I-III quotes
  // are real content (visible, AA-legal ash) and must remain in the a11y tree.
  const html = renderToStaticMarkup(<World />);
  const quotes = html.match(/<p[^>]*class="world__tx-quote[^"]*"[^>]*>/g) ?? [];
  const visible = quotes.filter((q) => !q.includes("world__tx-quote--redacted"));
  expect(visible.length).toBe(HOLLOW_TIERS.filter((t) => !t.redacted).length);
  for (const q of visible) expect(q).not.toContain("aria-hidden");
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<World />)).not.toThrow();
});
