import { NavBar } from "./components/NavBar.tsx";
import { Hero } from "./sections/Hero.tsx";
import { AudioDemo } from "./sections/AudioDemo.tsx";
import { Premise } from "./sections/Premise.tsx";
import { Footer } from "./components/Footer.tsx";

// The Divine Ruin marketing site: the above-the-fold sections (Hero, AudioDemo,
// Premise) composed under the NavBar + Footer chrome, in the mockup's order.
// Kept hydration-safe — no window/Date/random during render — because the same
// component is rendered on the server (build-time prerender) and hydrated on the
// client (client.tsx); identical markup on both sides prevents a React hydration
// mismatch. Each section imports its own co-located CSS, which Bun pulls into the
// bundle through this import graph.
export function App() {
  return (
    <>
      <NavBar />
      <Hero />
      <AudioDemo />
      <Premise />
      <Footer />
    </>
  );
}
