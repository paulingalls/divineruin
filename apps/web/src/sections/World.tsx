import "./World.css";
import { useReveal } from "../lib/useReveal.ts";

export interface TimelineEvent {
  year: string;
  title: string;
  desc: string;
  now?: boolean;
}

export interface Place {
  name: string;
  kind: string;
  status: string;
  desc: string;
}

export interface HollowTier {
  tier: string;
  threat: string;
  name: string;
  desc: string;
  quote: string;
  redacted?: boolean;
}

export interface MetaEntry {
  term: string;
  value: string;
  small: string;
}

export type PlaceStatusVariant = "held" | "lost" | "warn";

// Status -> color variant. Replaces the mockup's inline statusColor(); CSS owns the
// actual color/dot per .world__place-status--<variant>. "Lost" is a wound; the
// in-between states ("Bending"/"Contested"/"Held, barely") warn; everything else holds.
export function placeStatusVariant(status: string): PlaceStatusVariant {
  if (status === "Lost") return "lost";
  if (status === "Bending" || status === "Contested" || status === "Held, barely") return "warn";
  return "held";
}

// Verbatim from the mockup source (docs/mockups/source/sections-1.jsx, World).
export const WORLD_TIMELINE: readonly TimelineEvent[] = [
  {
    year: "Year −30",
    title: "The Sundering",
    desc: "In a single night, the Veil — the membrane between Aethos and what lies behind it — was torn. The great city of Aelindra unmade itself by dawn. The first Hollow walked at noon.",
  },
  {
    year: "Year −28",
    title: "The Five Accords",
    desc: "What was left of civilization gathered at the port of Tides and swore the Accords: shared borders, shared armies, and a careful, public agreement that no one was to blame.",
  },
  {
    year: "Year −12",
    title: "The Voidmaw stabilizes",
    desc: "The wound where Aelindra fell stops widening — but begins, on quiet nights, to whisper. Some who listen come back changed. Most do not come back.",
  },
  {
    year: "Year −3",
    title: "The Greyvale bends",
    desc: "Forests south of the Maw begin to grow in directions the seasons do not recognize. Birds learn songs no one taught them. A scout returns alone, speaking only in the voices of the others.",
  },
  {
    year: "Now",
    title: "The Veil thins again",
    desc: "Patrons stir. Oracles disagree. Something on the far side of the wound has started counting backwards. You arrive in Aethos with a name, a god, and one chance to be useful before the second tearing.",
    now: true,
  },
];

export const WORLD_PLACES: readonly Place[] = [
  {
    name: "Accord of Tides",
    kind: "Port capital",
    status: "Held",
    desc: "The last great city. Built on pylons over a harbor that never freezes. Half marketplace, half military barracks, all rumor.",
  },
  {
    name: "The Voidmaw",
    kind: "The wound",
    status: "Lost",
    desc: "Where Aelindra was. A spiral of nothing, a mile across, that the maps refuse to settle on. The closer you stand, the older you feel.",
  },
  {
    name: "The Greyvale",
    kind: "Corrupted wildland",
    status: "Bending",
    desc: "A forest belt south of the Maw, leaning slowly inward. Trees with the wrong number of branches. Useful, if you're brave, and bring witnesses.",
  },
  {
    name: "Ashen Reach",
    kind: "Mountain frontier",
    status: "Held, barely",
    desc: "Northern peaks. The old dwarven holds, now garrisons. The wind there carries arguments from a thousand years ago.",
  },
  {
    name: "The Hollow Marches",
    kind: "Frontier line",
    status: "Contested",
    desc: "The ring of forts and waystations where the Hollow is held, by spear and prayer and the patience of the Ironhand.",
  },
  {
    name: "Silent Library",
    kind: "Order seat",
    status: "Held",
    desc: "Veythar's keep. Every book ever written. Most of them lying about the same thirty days, thirty years ago.",
  },
];

export const HOLLOW_TIERS: readonly HollowTier[] = [
  {
    tier: "Tier I",
    threat: "Common · Low threat",
    name: "Drift",
    desc: "They move the way leaves move across pavement. No purpose, no direction. The pavement remembers them anyway.",
    quote:
      "“If the moths find you, walk. Don't run — they feed on panic. Walk fast, and get indoors.”",
  },
  {
    tier: "Tier II",
    threat: "Uncommon · Moderate",
    name: "Rend",
    desc: "Coherent enough to want. Coherent enough to wait. They arrange the room around you before they ever touch you.",
    quote:
      "“When the room doesn't sound right, stop walking. Finding the weaver before it finishes is the only thing that matters.”",
  },
  {
    tier: "Tier III",
    threat: "Rare · High",
    name: "Wrack",
    desc: "Each sighting is reported singly. They have weight in the world the way mountains do. They are still arriving.",
    quote: "“When your own voice stops sounding like you, fall back. You're inside its reach.”",
  },
  {
    tier: "Tier IV",
    threat: "Singular · Extreme",
    name: "The Named",
    desc: "There are not many. The Ashmark companies report them by name, the way you report a storm. Most live near the rim of the Voidmaw. They have not yet been provoked.",
    quote: "[ this passage has been crossed out ]",
    redacted: true,
  },
];

export const WORLD_META: readonly MetaEntry[] = [
  {
    term: "The Setting",
    value: "Aethos",
    small: "A continent. Ten gods. Five surviving civilizations.",
  },
  {
    term: "The Threat",
    value: "The Hollow",
    small: "Spreading from the Voidmaw, southward, every game-tick.",
  },
  {
    term: "The Mystery",
    value: "What tore the Veil?",
    small: "Buried in artifacts, contradictions, and forgotten lore.",
  },
];

// "03 / The World" section: Aethos, the Sundering, the Voidmaw, and the Hollow — the
// lore centerpiece. Lands id="world", the anchor the story-006 capstone re-points
// Hero's secondary CTA to. Progressive enhancement matches Premise/Session: all content
// is in the prerendered HTML and visible by default; only post-hydration (via useReveal)
// does the section arm and reveal its `.reveal-item` cards on scroll.
export function World() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="world" id="world" ref={sectionRef}>
      <div className="world__inner">
        <p className="world__eyebrow">
          <span className="world__eyebrow-num">03</span> The World
        </p>
        <h2 className="world__title">
          Aethos, <em>and the wound at its center.</em>
        </h2>
        <p className="world__lede">
          Ten gods tend a fantasy world that is running out of time. Thirty years ago the Veil
          shattered. The fallen city of Aelindra is now a wound in reality called the Voidmaw.
          Through it pours the Hollow — and the gods cannot agree on what the Hollow is.
        </p>

        <div className="world__alert">
          <div className="world__alert-label">Hollow corruption detected</div>
          <div className="world__alert-body">
            They do not speak. They do not negotiate. They consume.{" "}
            <em>
              Where they come from, and how they found their way through, no living thing in Aethos
              can agree.
            </em>
          </div>
        </div>

        <figure className="world__quote">
          <blockquote>
            We don't say the names of the lost out loud anymore. The Hollow listens for names.
          </blockquote>
          <figcaption>
            <span className="world__quote-who">A wall at the southern gate of the Ashmark</span>
            <span className="world__quote-when">scratched, undated</span>
          </figcaption>
        </figure>

        <div className="world__block">
          <div className="world__block-eyebrow">The Sundering — a record</div>
          <ol className="world__timeline">
            {WORLD_TIMELINE.map((ev) => (
              <li
                className={"world__tl-event reveal-item" + (ev.now ? " world__tl-event--now" : "")}
                key={ev.year}
              >
                <div className="world__tl-year">{ev.year}</div>
                <div className="world__tl-marker" aria-hidden="true" />
                <div className="world__tl-content">
                  <h3 className="world__tl-title">{ev.title}</h3>
                  <p className="world__tl-desc">{ev.desc}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="world__block">
          <div className="world__block-eyebrow">Where the world holds, and where it doesn't</div>
          <div className="world__places-grid">
            {WORLD_PLACES.map((p) => (
              <article className="world__place reveal-item" key={p.name}>
                <div className="world__place-head">
                  <span className="world__place-kind">{p.kind}</span>
                  <span
                    className={
                      "world__place-status world__place-status--" + placeStatusVariant(p.status)
                    }
                  >
                    <span className="world__place-dot" aria-hidden="true" />
                    {p.status}
                  </span>
                </div>
                <h3 className="world__place-name">{p.name}</h3>
                <p className="world__place-desc">{p.desc}</p>
              </article>
            ))}
          </div>
        </div>

        <div className="world__block">
          <div className="world__block-eyebrow">
            A field guide, copied without permission from an Ashmark wardroom
          </div>
          <ol className="world__taxonomy">
            {HOLLOW_TIERS.map((t, i) => (
              <li className={"world__tx reveal-item world__tx--" + (i + 1)} key={t.name}>
                <div className="world__tx-meta">
                  <span className="world__tx-tier">{t.tier}</span>
                  <span className="world__tx-threat">{t.threat}</span>
                </div>
                <h3 className="world__tx-name">{t.name}</h3>
                <p className="world__tx-desc">{t.desc}</p>
                <p
                  className={"world__tx-quote" + (t.redacted ? " world__tx-quote--redacted" : "")}
                  aria-hidden={t.redacted || undefined}
                >
                  {t.quote}
                </p>
              </li>
            ))}
          </ol>
        </div>

        <dl className="world__meta">
          {WORLD_META.map((m) => (
            <div key={m.term}>
              <dt>{m.term}</dt>
              <dd>
                {m.value}
                <span className="world__meta-small">{m.small}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
