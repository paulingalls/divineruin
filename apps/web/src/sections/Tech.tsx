import "./Tech.css";
import { useReveal } from "../lib/useReveal.ts";

export interface TechPartner {
  role: string;
  name: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-2.jsx, Tech).
export const TECH_PARTNERS: readonly TechPartner[] = [
  { role: "Transport", name: "LiveKit" },
  { role: "Speech-to-Text", name: "Deepgram" },
  { role: "Narrative LLM", name: "Claude" },
  { role: "Voice Synthesis", name: "Inworld" },
];

// Tech-credibility strip: the voice + AI stack behind the game. Progressive enhancement matches
// the sibling sections: the items are in the prerendered HTML and visible by default; only
// post-hydration (via useReveal) does the section arm and reveal its `.reveal-item` items.
export function Tech() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="tech" id="tech" ref={sectionRef}>
      <div className="tech__inner">
        {/* Visually-hidden heading: the strip leads with an eyebrow <p>, so this
            keeps the section in the screen-reader document outline (.sr-only). */}
        <h2 className="sr-only">Technology stack</h2>
        <p className="tech__eyebrow">Built on the best of 2026's voice and AI stack</p>
        <div className="tech__strip">
          {TECH_PARTNERS.map((t) => (
            <div className="tech__item reveal-item" key={t.name}>
              <div className="tech__role">{t.role}</div>
              <div className="tech__name">{t.name}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
