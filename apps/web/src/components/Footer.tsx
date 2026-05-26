// Site footer chrome shared by the build-time prerender and the client. Like
// App.tsx and NavBar.tsx it must render identical markup server + client, so
// the copy is fully static — no `new Date()` year, which would differ between
// the build and a client hydrating in a later year and cause a mismatch.
export function Footer() {
  return (
    <footer className="footer">
      <p className="footer__brand">Divine Ruin</p>
      <p className="footer__tagline">The Sundered Veil — an audio-first AI tabletop RPG.</p>
    </footer>
  );
}
