import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Hero } from "./Hero.tsx";

// Same no-DOM unit pattern as NavBar.test.tsx: renderToStaticMarkup runs with no
// window/DOM, so a clean render both checks the copy is in the prerendered markup
// (SEO/LCP — content visible without JS) and proves Hero is hydration-safe (a
// window/Date access during render would throw here). Live styling + the
// reduced-motion backdrop are CSS-only and covered by the story-005 capstone E2E.
// Copy is verbatim from the mockup source (docs/mockups/source/hero.jsx).

test("renders the brand headline with the italic 'Ruin' display treatment", () => {
  const html = renderToStaticMarkup(<Hero />);
  // Headline is "Divine" then a break then italic "Ruin", per the mockup.
  expect(html).toContain("<h1");
  expect(html).toMatch(/Divine<br\/?><em>Ruin<\/em>/);
});

test("renders the eyebrow meta — setting line and playtest status", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("Aethos · Year 30 of the Sundered Veil");
  expect(html).toContain("Pre-alpha · Closed playtest");
});

test("renders the subhead and the real pitch copy", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("the sundered veil");
  expect(html).toContain(
    "A fantasy RPG you play with your voice. A world tended by ten gods, threatened by something that should not exist, and narrated to you — in real time — by an AI Dungeon Master who voices every character, remembers every choice, and never reads from a script.",
  );
});

test("renders both CTAs with the mockup labels and functional targets", () => {
  const html = renderToStaticMarkup(<Hero />);
  // Primary -> #waitlist (lands M5; shared tracked anchor). Secondary "Enter
  // Aethos" -> #world, the World section (re-pointed from the M3 #premise
  // placeholder now that World ships id="world").
  expect(html).toMatch(/<a[^>]+href="#waitlist"[^>]*>[\s\S]*?Request Early Access/);
  expect(html).toMatch(/<a[^>]+href="#world"[^>]*>[\s\S]*?Enter Aethos/);
});

test("renders the bottom meta — voice-first / headphones / scroll cue", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("A voice-first audio RPG");
  expect(html).toContain("Headphones recommended");
  expect(html).toContain("Scroll");
});

test("renders hydration-safe markup (no window access during render)", () => {
  expect(() => renderToStaticMarkup(<Hero />)).not.toThrow();
});
