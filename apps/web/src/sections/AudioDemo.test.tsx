import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AudioDemo, AUDIO_SRC, WAVEFORM_BARS } from "./AudioDemo.tsx";

// Same no-DOM unit pattern as NavBar.test.tsx / Hero.test.tsx: renderToStaticMarkup
// runs with no window/DOM, so it checks the static markup and proves hydration
// safety (a DOM/audio access during render would throw). The play/pause *toggle*
// (click -> audio.play() -> state flips -> waveform animates) needs a live DOM and
// is covered by the story-005 capstone browser E2E, not here.

test("renders a labelled play control in the paused state", () => {
  const html = renderToStaticMarkup(<AudioDemo />);
  // Scope label + pressed-state to the same <button> so the assertion can't pass
  // on aria-pressed landing on some other element.
  expect(html).toMatch(/<button[^>]*aria-label="Play the sample"[^>]*aria-pressed="false"/);
  // The play glyph (not the pause glyph) must render in the paused state — guards
  // against a regression that keeps the paused label but shows the pause icon.
  expect(html).toContain("▶");
  expect(html).not.toContain("❚❚");
});

test("renders a lazy audio element pointing at the served sample", () => {
  const html = renderToStaticMarkup(<AudioDemo />);
  // preload="none" => the 1.3MB body isn't fetched until the user hits play
  // (not render-blocking). src is the stable served path the capstone copies to dist.
  expect(html).toMatch(/<audio[^>]+preload="none"/);
  expect(html).toContain(`src="${AUDIO_SRC}"`);
  expect(AUDIO_SRC).toBe("/audio/dm-sample.mp3");
});

test("renders one waveform bar per configured height", () => {
  const html = renderToStaticMarkup(<AudioDemo />);
  const bars = html.match(/class="audio-demo__bar"/g) ?? [];
  expect(bars.length).toBe(WAVEFORM_BARS.length);
});

test("starts paused — no playing modifier on the container", () => {
  const html = renderToStaticMarkup(<AudioDemo />);
  expect(html).not.toContain("audio-demo--playing");
});

test("WAVEFORM_BARS is a non-empty set of fractional heights in (0, 1]", () => {
  expect(WAVEFORM_BARS.length).toBeGreaterThan(0);
  for (const h of WAVEFORM_BARS) {
    expect(h).toBeGreaterThan(0);
    expect(h).toBeLessThanOrEqual(1);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<AudioDemo />)).not.toThrow();
});
