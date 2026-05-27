import "./Pricing.css";
import { useReveal } from "../lib/useReveal.ts";

export interface PricingPlan {
  eyebrow: string;
  currency: string;
  amount: string;
  per: string;
  includes: readonly string[];
  trial: string;
}

// Verbatim from the mockup source (docs/mockups/source/sections-2.jsx, Pricing).
export const PRICING: PricingPlan = {
  eyebrow: "Premium · Monthly",
  currency: "$",
  amount: "17",
  per: "/ month",
  includes: [
    "Unlimited live sessions with the AI Dungeon Master",
    "Async play between sessions — crafting, training, side quests",
    "Premium narration voices and expressive TTS",
    "Patron deity selection · all ten gods, all 18 archetypes",
    "Solo and small-party play · up to four friends in a session",
  ],
  trial: "7-day free trial · Cancel anytime",
};

// "07 / Subscription" section: the one-price pitch as a single subscription card, then the
// no-pay-to-win redline. Progressive enhancement matches the sibling sections: the card is in
// the prerendered HTML and visible by default; only post-hydration (via useReveal) does the
// section arm and reveal its `.reveal-item` card on scroll.
export function Pricing() {
  const sectionRef = useReveal<HTMLElement>();

  return (
    <section className="pricing" id="pricing" ref={sectionRef}>
      <div className="pricing__inner">
        <p className="pricing__eyebrow">
          <span className="pricing__eyebrow-num">07</span> Subscription
        </p>
        <h2 className="pricing__title">
          One price. <em>The whole world.</em>
        </h2>
        <p className="pricing__lede">
          A flat monthly subscription covers unlimited play, every patron path, and every voice your
          DM is going to need to summon.
        </p>

        <div className="pricing__card reveal-item">
          <div className="pricing__card-eyebrow">{PRICING.eyebrow}</div>
          <div className="pricing__amount">
            <span className="pricing__currency">{PRICING.currency}</span>
            <span className="pricing__num">{PRICING.amount}</span>
            <span className="pricing__per">{PRICING.per}</span>
          </div>
          <ul className="pricing__includes">
            {PRICING.includes.map((item) => (
              <li className="pricing__include" key={item}>
                {item}
              </li>
            ))}
          </ul>
          <div className="pricing__trial">{PRICING.trial}</div>
        </div>

        <p className="pricing__redline">
          No pay-to-win. No stat boosts. No grind skips. <br />
          Cosmetic, narrative, experiential — never mechanical.
        </p>
      </div>
    </section>
  );
}
