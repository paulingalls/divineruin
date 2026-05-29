import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AudioDemo, AUDIO_SRC, WAVEFORM_BARS, formatTime } from "./AudioDemo.tsx";

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

test("renders the session sample title (verbatim mockup copy)", () => {
  const html = renderToStaticMarkup(<AudioDemo />);
  expect(html).toContain("Hear a session — “The Greyvale Road”");
});

test("renders the time readout, zeroed before metadata loads (hydration-safe)", () => {
  // The real <audio> is preload="none", so duration is unknown until play; the
  // SSR/initial markup must show a deterministic zeroed readout (matching the
  // mockup's HH:MM:SS / HH:MM:SS time format) that the live element then updates.
  const html = renderToStaticMarkup(<AudioDemo />);
  expect(html).toContain("00:00:00 / 00:00:00");
});

test("formatTime renders whole seconds as zero-padded HH:MM:SS", () => {
  expect(formatTime(0)).toBe("00:00:00");
  expect(formatTime(5)).toBe("00:00:05");
  expect(formatTime(30)).toBe("00:00:30");
  expect(formatTime(65)).toBe("00:01:05");
  expect(formatTime(3661)).toBe("01:01:01");
  // Floors fractional seconds rather than rounding (a 4.9s position is still 0:04).
  expect(formatTime(4.9)).toBe("00:00:04");
});

test("formatTime treats unknown/invalid durations as zero", () => {
  // Before loadedmetadata the element's duration is NaN; a negative or Infinite
  // value must never leak into the readout.
  expect(formatTime(NaN)).toBe("00:00:00");
  expect(formatTime(Infinity)).toBe("00:00:00");
  expect(formatTime(-3)).toBe("00:00:00");
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

test("gives the section a heading for the document outline (visually hidden)", () => {
  // The demo's visible title is a styled <span>, not a heading — a section with
  // no heading is a hole in the screen-reader outline. Add a visually-hidden
  // <h2> so the h1 -> h2 outline stays gapless without changing the visual design.
  const html = renderToStaticMarkup(<AudioDemo />);
  expect(html).toMatch(/<h2[^>]*class="sr-only"[^>]*>Audio sample<\/h2>/);
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<AudioDemo />)).not.toThrow();
});
