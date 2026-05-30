import "./Faq.css";
import { useId, useState } from "react";

export interface FaqItem {
  q: string;
  a: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-2.jsx, FAQ).
export const FAQ_ITEMS: readonly FaqItem[] = [
  {
    q: "What do I need to play?",
    a: "A phone and a pair of headphones. The phone is a glanceable HUD; everything else happens out loud.",
  },
  {
    q: "Can I play solo, or do I need a group?",
    a: "Both. Solo with your AI companion and the Master, or with a party of up to four — real friends, real voices, in the same scene.",
  },
  {
    q: "I'm not great at improv. Will I freeze?",
    a: "The Master gives you space and follows your lead. Say one word or fifty; the world fills in around you. You'll find your voice in the first hour.",
  },
  {
    q: "How long is a session?",
    a: "Anywhere from five minutes to ninety. The Master scales the scene to the time you have. Five-minute stops by the campfire count.",
  },
  {
    q: "Will the Master remember me?",
    a: "Yes. Your name, your patron, the price you paid the smith three nights ago, the thing your companion said in the rain. The world keeps notes on you between sessions.",
  },
  {
    q: "How is this different from an AI chatbot?",
    a: "A chatbot improvises a scene. The Master runs a world — with rules, with consequences, with continuity. There are dice in this. There is a wound at the center.",
  },
  {
    q: "Can I play while doing other things?",
    a: "That is most of what this game is for. Walks. Commutes. Long quiet hours. Audio-first means your eyes are free for the dishes.",
  },
  {
    q: "When does it launch?",
    a: "Closed playtest waves through 2026, with broader access through 2027. Drop your email below and we'll send a Veil-key when your cohort opens.",
  },
];

// "08 / Questions" section: the FAQ as a single-open accordion. Interactive (not reveal-gated —
// matches the AudioDemo precedent; the grid-rows expand IS the animation). State is hydration-safe:
// openIdx starts at 0 so the server-rendered markup (first item open) matches the first client
// render. Each question is a real <button> (keyboard-operable by default) wired to its answer panel
// via aria-controls/aria-expanded for assistive tech. Clicking the open item closes all (-1).
export function Faq() {
  const [openIdx, setOpenIdx] = useState(0);
  const baseId = useId();

  return (
    <section className="faq" id="faq">
      <div className="faq__inner">
        <p className="faq__eyebrow">
          <span className="faq__eyebrow-num">08</span> Questions
        </p>
        <h2 className="faq__title">What you'll probably ask first.</h2>
        <p className="faq__lede">
          The Master answers in character, but here are the short versions.
        </p>

        <ul className="faq__list">
          {FAQ_ITEMS.map((item, i) => {
            const open = openIdx === i;
            const panelId = `${baseId}-panel-${i}`;
            const buttonId = `${baseId}-q-${i}`;
            return (
              <li className={"faq__item" + (open ? " faq__item--open" : "")} key={item.q}>
                <button
                  type="button"
                  id={buttonId}
                  className="faq__q"
                  aria-expanded={open}
                  aria-controls={panelId}
                  onClick={() => setOpenIdx(open ? -1 : i)}
                >
                  <span className="faq__q-num" aria-hidden="true">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="faq__q-text">{item.q}</span>
                  <span className="faq__q-toggle" aria-hidden="true">
                    {open ? "−" : "+"}
                  </span>
                </button>
                <div
                  className="faq__answer-wrap"
                  id={panelId}
                  role="region"
                  aria-labelledby={buttonId}
                >
                  <p className="faq__answer">{item.a}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
