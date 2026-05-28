import "./Pantheon.css";
import { useReveal } from "../lib/useReveal.ts";

export interface God {
  name: string;
  title: string;
  domain: string;
  quote: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-2.jsx, Pantheon).
export const GODS: readonly God[] = [
  {
    name: "Veythar",
    title: "the Lorekeeper",
    domain: "Knowledge / Memory",
    quote: "Every story has a story it does not tell. Be patient with mine.",
  },
  {
    name: "Mortaen",
    title: "the Threshold",
    domain: "Death / Transition",
    quote: "I am not your enemy. I am the door, and I have been waiting.",
  },
  {
    name: "Thyra",
    title: "the Wildmother",
    domain: "Nature / Seasons",
    quote: "The world does not ask to be saved. It asks to be heard.",
  },
  {
    name: "Kaelen",
    title: "the Ironhand",
    domain: "War / Valor",
    quote: "Courage is a craft. I will teach you, and you will pay.",
  },
  {
    name: "Syrath",
    title: "the Veilwatcher",
    domain: "Shadows / Secrets",
    quote: "Speak softly, child. I am listening to everyone.",
  },
  {
    name: "Aelora",
    title: "the Hearthkeeper",
    domain: "Civilization / Bonds",
    quote: "A hearth is a small light. Tend yours. The dark is large.",
  },
  {
    name: "Valdris",
    title: "the Scalebearer",
    domain: "Justice / Law",
    quote: "I do not weigh the heart. I weigh what the heart did.",
  },
  {
    name: "Nythera",
    title: "the Tidecaller",
    domain: "Sea / Horizons",
    quote: "Every map ends. Every voyage does not.",
  },
  {
    name: "Orenthel",
    title: "the Dawnbringer",
    domain: "Light / Healing",
    quote: "Rest. You are not finished, only resting.",
  },
  {
    name: "Zhael",
    title: "the Fatespinner",
    domain: "Fate / Time",
    quote: "You are a thread in my hand. I will not tighten it. I will not let go.",
  },
];

// "05 / The Pantheon" section: the ten gods as a card grid. Your patron flavors abilities,
// shapes quest lines, and whispers when the world turns. Progressive enhancement matches the
// sibling sections: all cards are in the prerendered HTML and visible by default; only
// post-hydration (via useReveal) does the section arm and reveal its `.reveal-item` cards.
export function Pantheon() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="pantheon" id="pantheon" ref={sectionRef}>
      <div className="pantheon__inner">
        <p className="pantheon__eyebrow">
          <span className="pantheon__eyebrow-num">05</span> The Pantheon
        </p>
        <h2 className="pantheon__title">
          Choose a patron. <em>Inherit a story.</em>
        </h2>
        <p className="pantheon__lede">
          Each of the ten gods has a will of their own. Your patron flavors your abilities, shapes
          your quest lines, and whispers in your ear when the world is about to turn.
        </p>

        <div className="pantheon__grid">
          {GODS.map((g, i) => (
            <article className="pantheon__card reveal-item" key={g.name}>
              <div className="pantheon__top">
                <div className="pantheon__num">{String(i + 1).padStart(2, "0")} / 10</div>
                <div className="pantheon__name">{g.name}</div>
                <div className="pantheon__god-title">{g.title}</div>
              </div>
              <div className="pantheon__quote">“{g.quote}”</div>
              <div className="pantheon__domain">{g.domain}</div>
            </article>
          ))}
        </div>

        <p className="pantheon__note">
          Ten gods. Ten different stories of the Sundering. None of them agree, and not one will
          yield.
        </p>
      </div>
    </section>
  );
}
