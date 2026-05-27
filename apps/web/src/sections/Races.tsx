import "./Races.css";
import { useReveal } from "../lib/useReveal.ts";

export interface Race {
  name: string;
  tagline: string;
  sense: string;
  flavor: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-2.jsx, Races).
export const RACES: readonly Race[] = [
  {
    name: "Draethar",
    tagline: "Forge-warm. Heavy-handed. Slow to anger, slower to leave.",
    sense: "The warmth radiating from dense, powerful hands.",
    flavor: "Mountain-folk and smiths. Their voices carry the way bell-iron carries.",
  },
  {
    name: "Elari",
    tagline: "Fine-boned. Vein-bright. Aware of what the air conceals.",
    sense: "Long, fine fingers that tingle with awareness of something beyond the visible.",
    flavor: "Once the keepers of the highest libraries. Long memories. Longer grudges.",
  },
  {
    name: "Korath",
    tagline: "Stone-skinned. Quiet. Older than most of what they remember.",
    sense: "Broad hands, skin with a faint mineral sheen, solid as the stone beneath you.",
    flavor: "From the deep holds beneath Ashen Reach. They speak when they have something to say.",
  },
  {
    name: "Vaelti",
    tagline: "Quick. Wind-attuned. Hear the rumor before the wind arrives.",
    sense: "Quick, nimble hands, every nerve alive to the air currents around them.",
    flavor: "Steppe-riders and scouts. The Hollow has tried to take them more than once.",
  },
  {
    name: "Thessyn",
    tagline: "Adaptable. Borrowed-shaped. Become what is needed.",
    sense: "Hands that feel… adaptable, as though they could become anything given time.",
    flavor: "Few in number, never twice the same. The gods are politely confused by them.",
  },
  {
    name: "Human",
    tagline: "Unremarkable, except for what is behind it.",
    sense: "Steady, capable hands — unremarkable except for the determination behind them.",
    flavor:
      "Outnumbering, outliving, outlasting. Tending the fires the world keeps trying to put out.",
  },
];

// "04 / The Peoples" section: the six playable races as a card grid. The DM opens your
// story by asking what your hands feel like, not by showing a menu. Progressive
// enhancement matches the sibling sections: all cards are in the prerendered HTML and
// visible by default; only post-hydration (via useReveal) does the section arm and reveal
// its `.reveal-item` cards on scroll.
export function Races() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="races" id="races" ref={sectionRef}>
      <div className="races__inner">
        <p className="races__eyebrow">
          <span className="races__eyebrow-num">04</span> The Peoples
        </p>
        <h2 className="races__title">
          Six peoples. <em>One world to outlive.</em>
        </h2>
        <p className="races__lede">
          The Master begins your story with a question, not a menu.{" "}
          <em>
            You open your eyes. The world sharpens around you. What do you see when you look at your
            hands?
          </em>
        </p>

        <div className="races__grid">
          {RACES.map((r, i) => (
            <article className="races__card reveal-item" key={r.name}>
              <div className="races__num">{String(i + 1).padStart(2, "0")} / 06</div>
              <h3 className="races__name">{r.name}</h3>
              <p className="races__sense">“{r.sense}”</p>
              <p className="races__tagline">{r.tagline}</p>
              <p className="races__flavor">{r.flavor}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
