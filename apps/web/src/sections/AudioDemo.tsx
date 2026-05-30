import "./AudioDemo.css";
import { useRef, useState } from "react";

// Stable served path for the DM-narration sample. The asset lives at
// src/audio/dm-sample.mp3 and is copied verbatim into dist/audio/ at build time
// (the story-005 capstone adds the copy step to prerender.ts, mirroring how the
// woff2 fonts are served — kept out of Bun's bundler). A plain path string (not a
// JS import) keeps this out of the base64 inliner and needs no asset type decl.
export const AUDIO_SRC = "/audio/dm-sample.mp3";

// Decorative waveform bar heights (fraction of the track height). Deterministic —
// NOT random — so the server and client render identical markup (no hydration
// mismatch). Exported so the bar set is unit-testable without a DOM.
export const WAVEFORM_BARS: readonly number[] = [
  0.3, 0.55, 0.8, 0.45, 0.65, 1.0, 0.7, 0.4, 0.6, 0.85, 0.5, 0.35, 0.75, 0.9, 0.6, 0.45, 0.8, 0.55,
  0.3, 0.7, 0.95, 0.5, 0.65, 0.4, 0.75, 0.6, 0.85, 0.35,
];

// Formats a seconds offset as zero-padded HH:MM:SS (the mockup's time format).
// Unknown/invalid inputs (NaN before loadedmetadata, negative, Infinity) clamp to
// zero so the readout never shows garbage. Pure + exported for unit testing.
export function formatTime(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(safe / 3600))}:${pad(Math.floor((safe % 3600) / 60))}:${pad(safe % 60)}`;
}

// Audio-first interactive teaser: a play/pause control that plays a DM-narration
// sample, with a waveform that reflects the playing state. Hydration-safe — the
// initial paused state matches SSR and the audio element is touched only inside
// the click handler (post-hydration), the established NavBar pattern. The sample
// is lazy (preload="none"): nothing is fetched until the user presses play.
export function AudioDemo() {
  const [playing, setPlaying] = useState(false);
  // Live playback position + clip length, mirrored from the real <audio> element's
  // own events so the readout can't desync. Both start 0 to match SSR (preload is
  // "none", so duration is genuinely unknown until the user plays) — the listeners
  // fire only post-hydration, the established hydration-safe pattern.
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) {
      // play() rejects on a failed load (e.g. missing/decoding asset) or a
      // blocked autoplay gesture. Without this catch the promise rejection is
      // unhandled and the UI stays stuck "on" with no audio — reset to paused.
      el.play().catch(() => setPlaying(false));
    } else {
      el.pause();
    }
  };

  return (
    <section className={playing ? "audio-demo audio-demo--playing" : "audio-demo"}>
      {/* Visually-hidden heading: the visible title is a styled <span>, so this
          keeps the section in the screen-reader document outline (.sr-only). */}
      <h2 className="sr-only">Audio sample</h2>
      <button
        type="button"
        className="audio-demo__play"
        aria-label={playing ? "Pause the sample" : "Play the sample"}
        aria-pressed={playing}
        onClick={toggle}
      >
        {/* Icon swaps with state; decorative, the button carries the label. */}
        <span className="audio-demo__icon" aria-hidden="true">
          {playing ? "❚❚" : "▶"}
        </span>
      </button>
      <div className="audio-demo__info">
        <div className="audio-demo__label">
          <span className="audio-demo__title">Hear a session — “The Greyvale Road”</span>
          <span className="audio-demo__time">
            {formatTime(current)} / {formatTime(duration)}
          </span>
        </div>
        <div className="audio-demo__waveform" aria-hidden="true">
          {WAVEFORM_BARS.map((height, i) => (
            <span
              key={i}
              className="audio-demo__bar"
              style={{ height: `${Math.round(height * 100)}%` }}
            />
          ))}
        </div>
      </div>
      {/* State tracks the element's own events, so the UI can't desync from real
          playback (e.g. when the clip ends). */}
      <audio
        ref={audioRef}
        src={AUDIO_SRC}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => setPlaying(false)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
      />
    </section>
  );
}
