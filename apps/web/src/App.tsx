import { NavBar } from "./components/NavBar.tsx";
import { Hero } from "./sections/Hero.tsx";
import { Premise } from "./sections/Premise.tsx";
import { Session } from "./sections/Session.tsx";
import { World } from "./sections/World.tsx";
import { Races } from "./sections/Races.tsx";
import { Pantheon } from "./sections/Pantheon.tsx";
import { Classes } from "./sections/Classes.tsx";
import { Tech } from "./sections/Tech.tsx";
import { Pricing } from "./sections/Pricing.tsx";
import { Faq } from "./sections/Faq.tsx";
import { Waitlist } from "./sections/Waitlist.tsx";
import { Footer } from "./components/Footer.tsx";

// The Divine Ruin marketing site, composed in the mockup's order under the NavBar +
// Footer chrome: the above-the-fold Hero (which nests the AudioDemo card), then the Milestone 4 lore /
// feature sections (Session, World, Races, Pantheon, Classes, Tech), then the Milestone 5
// conversion sections (Pricing, FAQ, Waitlist). Mounting Waitlist here lands its
// id="waitlist", making the NavBar + Hero #waitlist CTAs live. Kept hydration-safe — no
// window/Date/random during render — because the same component is rendered on the server
// (build-time prerender) and hydrated on the client (client.tsx); identical markup on both
// sides prevents a React hydration mismatch. Each section imports its own co-located CSS,
// which Bun pulls into the bundle through this import graph.
export function App() {
  return (
    <>
      {/* Skip-to-content link: the first focusable element so a keyboard user can
          bypass the NavBar straight to the content (WCAG 2.4.1). Visually hidden
          until focused (.skip-link in styles.css). The content lives in a single
          <main> landmark; tabIndex={-1} lets the link move focus into it. */}
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <NavBar />
      <main id="main-content" tabIndex={-1}>
        {/* Hero renders the AudioDemo card inside itself, captioned with the
            voice-first / "Headphones recommended" note. */}
        <Hero />
        <Premise />
        <Session />
        <World />
        <Races />
        <Pantheon />
        <Classes />
        <Tech />
        <Pricing />
        <Faq />
        <Waitlist />
      </main>
      <Footer />
    </>
  );
}
