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
  // Each half splits into a nowrap "<key> ." + a detail so the eyebrow breaks after
  // the "." (not mid-phrase) on narrow screens - see Hero.css. Assert both pieces of
  // each half render in key->detail order, AND that the key keeps a trailing
  // non-breaking space (rendered &nbsp;, \u00a0) before the detail: a flex container
  // drops a whitespace-only text node between items, so the separator space lives
  // inside the key span to stay in the accessibility tree / copy-paste.
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toMatch(
    /hero__meta-key">\u25b8 Aethos \u00b7\u00a0<\/span>[\s\S]*hero__meta-detail">Year 30 of the Sundered Veil</,
  );
  expect(html).toMatch(
    /hero__meta-key">Pre-alpha \u00b7\u00a0<\/span>[\s\S]*hero__meta-detail">Closed playtest</,
  );
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

test("captions the audio sample with the voice-first / headphones note (no scroll cue)", () => {
  // The voice-first + headphones note now sits as a caption directly under the
  // audio sample card. The mockup's bottom-meta row and its "Scroll" cue were
  // dropped — everyone knows to scroll, and the note pairs naturally with the
  // sample it describes.
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("A voice-first audio RPG");
  expect(html).toContain("Headphones recommended");
  // The note renders after the audio card (it captions it).
  expect(html).toMatch(/audio-demo[\s\S]*hero__audio-caption/);
  // The scroll cue is gone.
  expect(html).not.toContain("Scroll");
});

test("nests the audio sample teaser inside the hero (mockup arrangement)", () => {
  // The mockup places the AudioDemo card inside the hero, just above the bottom
  // meta — so "Headphones recommended" sits right by the audio example. The card
  // (.audio-demo) must therefore render within the hero's markup.
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("audio-demo");
  expect(html).toContain("Hear a session — “The Greyvale Road”");
});

test("renders hydration-safe markup (no window access during render)", () => {
  expect(() => renderToStaticMarkup(<Hero />)).not.toThrow();
});
