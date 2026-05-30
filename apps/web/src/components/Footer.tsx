// Site footer chrome shared by the build-time prerender and the client. Like
// App.tsx and NavBar.tsx it must render identical markup server + client, so
// the copy is fully static. The copyright year is a STATIC literal — NOT a
// `new Date()` year, which would differ between the build and a client hydrating
// in a later year and cause a hydration mismatch. Structure mirrors the mockup
// (docs/mockups/source/sections-2.jsx), but only the live in-page links are
// wired — the mockup's dead href="#" "Deeper Docs"/"Company" columns are dropped.
export function Footer() {
  return (
    <footer className="footer">
      <div className="footer__grid">
        <div className="footer__brand">
          <p className="footer__logo">Divine Ruin</p>
          <p>
            A voice-first audio RPG set in Aethos, a world thirty years into a war it does not
            understand.
          </p>
        </div>
        <nav className="footer__col" aria-label="Site">
          {/* h3, not h4: the deepest heading before the footer is the section
              <h2>s, so h3 keeps the screen-reader outline gapless (same reason
              AudioDemo/Tech add sr-only <h2>s). axe heading-order is a
              best-practice rule outside the gate's wcag tag set, but the gapless
              outline is a codebase convention regardless. */}
          <h3>The Game</h3>
          <ul>
            <li>
              <a href="#world">The World</a>
            </li>
            <li>
              <a href="#pantheon">The Pantheon</a>
            </li>
            <li>
              <a href="#pricing">Subscribe</a>
            </li>
          </ul>
        </nav>
      </div>
      <div className="footer__base">
        <span>© 2026 PI Innovations, LLC</span>
        <span>Crafted in ink &amp; signal</span>
      </div>
    </footer>
  );
}
