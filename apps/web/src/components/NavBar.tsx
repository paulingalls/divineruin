import { useEffect, useState } from "react";

// Past this many pixels of vertical scroll the NavBar switches to its denser
// "scrolled" appearance. Exported so the threshold is unit-testable without a
// DOM (the live scroll transition is covered by Playwright).
export const SCROLL_THRESHOLD_PX = 40;

export function isScrolledPast(scrollY: number): boolean {
  return scrollY > SCROLL_THRESHOLD_PX;
}

// Site chrome shared by the build-time prerender and the client. Like App.tsx
// it must render identical markup server + client, so the scroll state starts
// `false` (matching SSR) and the window scroll listener is attached only after
// hydration inside useEffect — never during render.
export function NavBar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(isScrolledPast(window.scrollY));
    onScroll(); // sync once in case the page loads already scrolled
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className={scrolled ? "navbar navbar--scrolled" : "navbar"} aria-label="Primary">
      {/* Brand is a link, not a heading, so the hero <h1> stays the only
          heading on the page. */}
      <a className="navbar__brand" href="/">
        Divine Ruin
      </a>
      {/* Center links to the live in-page sections (text is uppercased in CSS,
          matching the mockup). Targets resolve to ids mounted in App.tsx. */}
      <ul className="navbar__links">
        <li>
          <a href="#world">World</a>
        </li>
        <li>
          <a href="#pantheon">Pantheon</a>
        </li>
        <li>
          <a href="#faq">Questions</a>
        </li>
        <li>
          <a href="#pricing">Subscribe</a>
        </li>
      </ul>
      <a className="navbar__cta" href="#waitlist">
        Request Early Access
      </a>
    </nav>
  );
}
