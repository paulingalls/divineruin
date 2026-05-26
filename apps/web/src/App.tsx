import { NavBar } from "./components/NavBar.tsx";
import { Footer } from "./components/Footer.tsx";

// Placeholder hero for the Divine Ruin marketing site, wrapped in the NavBar +
// Footer chrome. Kept hydration-safe — no window/Date/random access during
// render — because the same component is rendered on the server (build-time
// prerender, story-002) and hydrated on the client (client.tsx). Identical
// markup on both sides is what prevents a React hydration mismatch.
export function App() {
  return (
    <>
      <NavBar />
      <main>
        <h1>Divine Ruin</h1>
        <p>An audio-first AI tabletop RPG. Speak, and the world answers.</p>
        <p>Join the waitlist.</p>
      </main>
      <Footer />
    </>
  );
}
