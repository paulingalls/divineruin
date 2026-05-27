import "./Classes.css";
import { useEffect, useRef } from "react";
import { reveal, defaultRevealEnv } from "../lib/reveal.ts";

// The headline figures, kept as one consistent constant: total = archetypes * gods.
export const CLASSES_STAT = {
  archetypes: 18,
  gods: 10,
  total: 180,
} as const;

// "06 / The Build" section: the "big number" pitch — 18 archetypes × 10 patrons = 180 ways to
// play, because your patron rewrites your spellbook and quest log. Progressive enhancement
// matches the sibling sections: the stat is in the prerendered HTML and visible by default;
// only post-hydration (JS + IO) does the section arm and reveal it on scroll.
export function Classes() {
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    const env = defaultRevealEnv();
    if (!section || !env.IntersectionObserver) return;
    section.classList.add("classes--armed");
    return reveal(section.querySelectorAll(".classes__stat"), env);
  }, []);

  return (
    <section className="classes" id="classes" ref={sectionRef}>
      <div className="classes__inner">
        <p className="classes__eyebrow">
          <span className="classes__eyebrow-num">06</span> The Build
        </p>
        <h2 className="classes__title">
          Eighteen archetypes. <em>Ten patrons.</em>
        </h2>
        <div className="classes__stat">
          <div className="classes__big-num">{CLASSES_STAT.total}</div>
          <p className="classes__equation">
            <span className="classes__acc">{CLASSES_STAT.archetypes}</span> archetypes ×{" "}
            <span className="classes__acc">{CLASSES_STAT.gods}</span> gods ={" "}
            <span className="classes__acc">{CLASSES_STAT.total}</span> ways to play
          </p>
          <p className="classes__ctx">
            A Rogue who serves the god of justice is not the same character as a Rogue who serves
            the god of shadows. Your patron rewrites your spellbook, your quest log, and what the
            world asks of you.
          </p>
        </div>
      </div>
    </section>
  );
}
