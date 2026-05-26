import "./Hero.css";

// Above-the-fold landing section and the page's LCP element. Renders identical
// markup server (build-time prerender) and client (hydration) — no window/Date/
// random during render — so the headline and copy are in the prerendered HTML
// (good LCP, visible without JS). The only motion is the decorative rift/bloom
// backdrop, which animates via CSS post-paint and is disabled under
// prefers-reduced-motion; the content itself never depends on JS to be seen, so
// it deliberately does NOT use the scroll-reveal helper (revealing above-the-fold
// content would delay LCP).
export function Hero() {
  return (
    <section className="hero">
      {/* Decorative rift + bloom; aria-hidden so the backdrop isn't announced and
          the single <h1> stays the section's only semantic landmark. */}
      <div className="hero__backdrop" aria-hidden="true" />
      <div className="hero__content">
        <h1 className="hero__headline">
          Divine <em>Ruin</em>
        </h1>
        <p className="hero__subhead">the sundered veil</p>
        <p className="hero__pitch">An audio-first AI tabletop RPG. Speak, and the world answers.</p>
        <div className="hero__cta-row">
          {/* Shares the NavBar's #waitlist target — the in-page section lands in
              M5; until then this is the same known, tracked anchor, not a new
              dead link. */}
          <a className="hero__cta hero__cta--accent" href="#waitlist">
            Join the waitlist
          </a>
        </div>
      </div>
    </section>
  );
}
