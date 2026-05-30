import "./Session.css";
import { useReveal } from "../lib/useReveal.ts";

export type TranscriptVariant = "" | "player" | "combat" | "god";

export interface TranscriptLine {
  who: string;
  what: string;
  variant: TranscriptVariant;
}

// Verbatim from the mockup source (docs/mockups/source/sections-1.jsx, Session).
// The mockup's `cls` field is renamed `variant` here; the CSS maps it to a modifier.
export const SESSION_LINES: readonly TranscriptLine[] = [
  {
    who: "Narrator",
    what: "The Accord of Tides at dusk. Waves against the harbor wall. Vendors closing stalls. Somewhere behind you, a lute is tuning itself into a song that should not be familiar.",
    variant: "",
  },
  {
    who: "You",
    what: "I want to find the blacksmith.",
    variant: "player",
  },
  {
    who: "Narrator",
    what: "You weave through the market. The forge fire is already banked when you arrive — Halric the smith looks up, recognizes you, and slides the sword across the bench. He remembers you commissioned it three nights ago.",
    variant: "",
  },
  {
    who: "Halric",
    what: "“Steel sang true. Forty silver, as agreed. And mind the Greyvale — two parties came back today. Only one party.”",
    variant: "",
  },
  {
    who: "You",
    what: "I pay him and head for the tavern to meet my party.",
    variant: "player",
  },
  {
    who: "Combat",
    what: "Something moves in the treeline. Three shapes. They do not speak. They do not breathe.",
    variant: "combat",
  },
  {
    who: "Veythar",
    what: "“Child. The wound in the world widens. Look closer at what you found yesterday — the ledger lied.”",
    variant: "god",
  },
];

// "02 / A Session" section: a DM-voice transcript demo — narrator, player, NPC,
// combat, and a god, all "voiced" in one continuous scene. Shows the audio-first
// product promise to a marketing visitor.
//
// Progressive enhancement (matches Premise): the transcript lines are always in the
// prerendered HTML and visible by default. Only after hydration (via useReveal) does
// the section arm and reveal its `.reveal-item` lines on scroll. So with no JS, no
// IntersectionObserver, or reduced motion the content stays fully visible.
export function Session() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="session" id="session" ref={sectionRef}>
      <div className="session__inner">
        <p className="session__eyebrow">
          <span className="session__eyebrow-num">02</span> A Session
        </p>
        <h2 className="session__title">
          You speak. <em>The world speaks back.</em>
        </h2>
        <p className="session__lede">
          Every word below is generated and voiced in real time. The narrator, the smith, the god —
          different voices, one continuous scene, in your ear.
        </p>
        <div className="session__transcript">
          {SESSION_LINES.map((line, i) => (
            <div
              className={
                "session__line reveal-item" +
                (line.variant ? " session__line--" + line.variant : "")
              }
              key={i}
            >
              <span className="session__who">{line.who}</span>
              <span className="session__what">{line.what}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
