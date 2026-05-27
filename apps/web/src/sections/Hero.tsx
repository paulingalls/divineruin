import "./Hero.css";

// Above-the-fold landing section and the page's LCP element. Renders identical
// markup server (build-time prerender) and client (hydration) — no window/Date/
// random during render — so the headline and copy are in the prerendered HTML
// (good LCP, visible without JS). The only motion is the decorative rift/bloom
// backdrop + the live-dot pulse, which animate via CSS post-paint and are
// disabled under prefers-reduced-motion; the content never depends on JS to be
// seen, so it deliberately does NOT use the scroll-reveal helper (revealing
// above-the-fold content would delay LCP). Copy is verbatim from the mockup
// source (docs/mockups/source/hero.jsx).
export function Hero() {
  return (
    <header className="hero" id="top">
      {/* Decorative rift + bloom; aria-hidden so the backdrop isn't announced and
          the single <h1> stays the section's only semantic landmark. */}
      <div className="hero__backdrop" aria-hidden="true" />

      <div className="hero__meta">
        <span className="hero__meta-label">▸ Aethos · Year 30 of the Sundered Veil</span>
        <span className="hero__meta-status">
          <span className="hero__live-dot" aria-hidden="true" />
          Pre-alpha · Closed playtest
        </span>
      </div>

      <div className="hero__content">
        <h1 className="hero__headline">
          Divine
          <br />
          <em>Ruin</em>
        </h1>
        <p className="hero__subhead">the sundered veil</p>
        <p className="hero__pitch">
          A fantasy RPG you play with your voice. A world tended by ten gods, threatened by
          something that should not exist, and narrated to you — in real time — by an AI Dungeon
          Master who voices every character, remembers every choice, and never reads from a script.
        </p>

        <div className="hero__cta-row">
          {/* Primary -> #waitlist (in-page section lands in M5; same known,
              tracked anchor the NavBar uses). */}
          <a className="hero__cta hero__cta--accent" href="#waitlist">
            Request Early Access
          </a>
          {/* Secondary "Enter Aethos" scrolls into the content — targets #world, the
              World section (Milestone 4). Re-pointed from the M3 #premise placeholder
              now that the World section lands id="world". */}
          <a className="hero__cta hero__cta--ghost" href="#world">
            Enter Aethos ↓
          </a>
        </div>
      </div>

      <div className="hero__footer-meta">
        <div>
          <div className="hero__footer-label">A voice-first audio RPG</div>
          <div className="hero__footer-value">Headphones recommended</div>
        </div>
        <div className="hero__footer-scroll">
          <div className="hero__footer-label">Scroll</div>
          <div className="hero__footer-arrows" aria-hidden="true">
            ↓ ↓ ↓
          </div>
        </div>
      </div>
    </header>
  );
}
