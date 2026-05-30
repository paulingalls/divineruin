import "./Premise.css";
import { useReveal } from "../lib/useReveal.ts";

export interface PremiseItem {
  num: string;
  label: string;
  desc: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-1.jsx).
export const PREMISE_ITEMS: readonly PremiseItem[] = [
  {
    num: "01",
    label: "Voice-first",
    desc: "You speak, the world answers. No buttons. No menus. The phone is a glanceable HUD; your voice is the input.",
  },
  {
    num: "02",
    label: "Solo or with friends",
    desc: "Play alone with an AI companion, or bring a party of up to four. Real voices in your ear, around a virtual table, anywhere.",
  },
  {
    num: "03",
    label: "An AI Dungeon Master, all your own",
    desc: "Personal narrator. Voices every NPC. Adapts to everything you do. Remembers what happened three sessions ago.",
  },
  {
    num: "04",
    label: "A persistent mystery",
    desc: "Thirty years ago the Veil shattered. The gods have offered ten different explanations — and the truth is buried in artifacts, contradictions, and pieces of forgotten lore scattered across the world.",
  },
];

// "01 / The Premise" section: the voice-first / solo-or-party pitch as a numbered
// list. The one above-the-fold section that uses the scroll-reveal helper.
//
// Progressive enhancement: the cards are always in the prerendered HTML and
// visible by default. Only after hydration (via useReveal) does the section
// "arm" and reveal its `.reveal-item` cards on scroll — so with no JS, no
// IntersectionObserver, or reduced motion the content stays fully visible. Premise
// sits below the fold (after the 100vh hero + audio demo), so arming-then-revealing
// is never visible as a flash.
export function Premise() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="premise" id="premise" ref={sectionRef}>
      <div className="premise__inner">
        <p className="premise__eyebrow">
          <span className="premise__eyebrow-num">01</span> The Premise
        </p>
        <h2 className="premise__title">
          Put on headphones. <em>Enter a living world.</em>
        </h2>
        <p className="premise__lede">
          Divine Ruin is a voice-first fantasy RPG. Imagine an Audible novel that listens back —
          every NPC voiced, every scene improvised, every choice yours. Play solo or with a party of
          up to four, anywhere you can wear headphones.
        </p>
        <ul className="premise__list">
          {PREMISE_ITEMS.map((it) => (
            <li className="premise__item reveal-item" key={it.num}>
              <span className="premise__num">{it.num}</span>
              <div className="premise__body">
                <div className="premise__label">{it.label}</div>
                <div className="premise__desc">{it.desc}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
