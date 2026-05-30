/* global React */

// ============================================================
// Races of Aethos
// ============================================================
function Races() {
  const races = [
    {
      name: "Draethar",
      tagline: "Forge-warm. Heavy-handed. Slow to anger, slower to leave.",
      sense: "The warmth radiating from dense, powerful hands.",
      flavor: "Mountain-folk and smiths. Their voices carry the way bell-iron carries."
    },
    {
      name: "Elari",
      tagline: "Fine-boned. Vein-bright. Aware of what the air conceals.",
      sense: "Long, fine fingers that tingle with awareness of something beyond the visible.",
      flavor: "Once the keepers of the highest libraries. Long memories. Longer grudges."
    },
    {
      name: "Korath",
      tagline: "Stone-skinned. Quiet. Older than most of what they remember.",
      sense: "Broad hands, skin with a faint mineral sheen, solid as the stone beneath you.",
      flavor: "From the deep holds beneath Ashen Reach. They speak when they have something to say."
    },
    {
      name: "Vaelti",
      tagline: "Quick. Wind-attuned. Hear the rumor before the wind arrives.",
      sense: "Quick, nimble hands, every nerve alive to the air currents around them.",
      flavor: "Steppe-riders and scouts. The Hollow has tried to take them more than once."
    },
    {
      name: "Thessyn",
      tagline: "Adaptable. Borrowed-shaped. Become what is needed.",
      sense: "Hands that feel… adaptable, as though they could become anything given time.",
      flavor: "Few in number, never twice the same. The gods are politely confused by them."
    },
    {
      name: "Human",
      tagline: "Unremarkable, except for what is behind it.",
      sense: "Steady, capable hands — unremarkable except for the determination behind them.",
      flavor: "Outnumbering, outliving, outlasting. Tending the fires the world keeps trying to put out."
    }
  ];
  return (
    <section className="section" id="races">
      <div className="container">
        <div className="section-num"><span>04</span> The Peoples</div>
        <h2 className="section-title">
          Six peoples. <em>One world to outlive.</em>
        </h2>
        <p className="section-lede">
          The Master begins your story with a question, not a menu. <em>You open your eyes. The world sharpens around you. What do you see when you look at your hands?</em>
        </p>

        <div className="races-grid">
          {races.map((r, i) => (
            <article className="race" key={r.name}>
              <div className="race-num">{String(i + 1).padStart(2, '0')} / 06</div>
              <h3 className="race-name">{r.name}</h3>
              <p className="race-sense">&ldquo;{r.sense}&rdquo;</p>
              <p className="race-tagline">{r.tagline}</p>
              <p className="race-flavor">{r.flavor}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

// ============================================================
// Pantheon
// ============================================================
function Pantheon() {
  const gods = [
    {
      name: "Veythar",
      title: "the Lorekeeper",
      domain: "Knowledge / Memory",
      quote: "Every story has a story it does not tell. Be patient with mine."
    },
    {
      name: "Mortaen",
      title: "the Threshold",
      domain: "Death / Transition",
      quote: "I am not your enemy. I am the door, and I have been waiting."
    },
    {
      name: "Thyra",
      title: "the Wildmother",
      domain: "Nature / Seasons",
      quote: "The world does not ask to be saved. It asks to be heard."
    },
    {
      name: "Kaelen",
      title: "the Ironhand",
      domain: "War / Valor",
      quote: "Courage is a craft. I will teach you, and you will pay."
    },
    {
      name: "Syrath",
      title: "the Veilwatcher",
      domain: "Shadows / Secrets",
      quote: "Speak softly, child. I am listening to everyone."
    },
    {
      name: "Aelora",
      title: "the Hearthkeeper",
      domain: "Civilization / Bonds",
      quote: "A hearth is a small light. Tend yours. The dark is large."
    },
    {
      name: "Valdris",
      title: "the Scalebearer",
      domain: "Justice / Law",
      quote: "I do not weigh the heart. I weigh what the heart did."
    },
    {
      name: "Nythera",
      title: "the Tidecaller",
      domain: "Sea / Horizons",
      quote: "Every map ends. Every voyage does not."
    },
    {
      name: "Orenthel",
      title: "the Dawnbringer",
      domain: "Light / Healing",
      quote: "Rest. You are not finished, only resting."
    },
    {
      name: "Zhael",
      title: "the Fatespinner",
      domain: "Fate / Time",
      quote: "You are a thread in my hand. I will not tighten it. I will not let go."
    }
  ];
  return (
    <section className="section" id="pantheon" style={{ background: 'linear-gradient(180deg, var(--color-void), #0B0A0C 50%, var(--color-void))' }}>
      <div className="container">
        <div className="section-num"><span>05</span> The Pantheon</div>
        <h2 className="section-title">
          Choose a patron. <em>Inherit a story.</em>
        </h2>
        <p className="section-lede">
          Each of the ten gods has a will of their own. Your patron flavors your abilities, shapes your quest lines, and whispers in your ear when the world is about to turn.
        </p>

        <div className="pantheon-grid">
          {gods.map((g, i) => (
            <article className="god" key={g.name} tabIndex={0}>
              <div className="god-top">
                <div className="god-num">{String(i + 1).padStart(2, '0')} / 10</div>
                <div className="god-name">{g.name}</div>
                <div className="god-title">{g.title}</div>
              </div>
              <div className="god-quote">&ldquo;{g.quote}&rdquo;</div>
              <div className="god-domain">{g.domain}</div>
            </article>
          ))}
        </div>

        <p className="pantheon-note">
          Ten gods. Ten different stories of the Sundering. None of them agree, and not one will yield.
        </p>
      </div>
    </section>
  );
}

// ============================================================
// Classes — the big number
// ============================================================
function Classes() {
  return (
    <section className="section" id="classes">
      <div className="container">
        <div className="section-num"><span>06</span> The Build</div>
        <h2 className="section-title">
          Eighteen archetypes. <em>Ten patrons.</em>
        </h2>
        <div className="classes-stat">
          <div className="big-num">180</div>
          <div className="equation">
            <span className="acc">18</span>
            <span>&nbsp;archetypes&nbsp;</span>
            <span>×</span>
            <span>&nbsp;</span>
            <span className="acc">10</span>
            <span>&nbsp;gods&nbsp;</span>
            <span>=</span>
            <span>&nbsp;</span>
            <span className="acc">180</span>
            <span>&nbsp;ways to play</span>
          </div>
          <p className="ctx">
            A Rogue who serves the god of justice is not the same character as a Rogue who serves the god of shadows. Your patron rewrites your spellbook, your quest log, and what the world asks of you.
          </p>
        </div>
      </div>
    </section>
  );
}

// ============================================================
// Tech credibility
// ============================================================
function Tech() {
  const items = [
    { role: "Transport", name: "LiveKit" },
    { role: "Speech-to-Text", name: "Deepgram" },
    { role: "Narrative LLM", name: "Claude" },
    { role: "Voice Synthesis", name: "Inworld" }
  ];
  return (
    <section className="section" id="tech" style={{ paddingTop: 80, paddingBottom: 80 }}>
      <div className="container">
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <span className="t-mono">Built on the best of 2026's voice and AI stack</span>
        </div>
        <div className="tech-strip">
          {items.map(t => (
            <div className="tech-item" key={t.name}>
              <div className="role">{t.role}</div>
              <div className="name">{t.name}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ============================================================
// Pricing
// ============================================================
function Pricing() {
  return (
    <section className="section" id="pricing">
      <div className="container">
        <div className="section-num"><span>07</span> Subscription</div>
        <h2 className="section-title">
          One price. <em>The whole world.</em>
        </h2>
        <p className="section-lede">
          A flat monthly subscription covers unlimited play, every patron path, and every voice your DM is going to need to summon.
        </p>

        <div className="pricing-card">
          <div className="pricing-eyebrow">Premium · Monthly</div>
          <div className="pricing-amount">
            <span className="currency">$</span>
            <span className="num">17</span>
            <span className="per">/ month</span>
          </div>
          <ul className="pricing-includes">
            <li>Unlimited live sessions with the AI Dungeon Master</li>
            <li>Async play between sessions — crafting, training, side quests</li>
            <li>Premium narration voices and expressive TTS</li>
            <li>Patron deity selection · all ten gods, all 18 archetypes</li>
            <li>Solo and small-party play · up to four friends in a session</li>
          </ul>
          <div className="pricing-trial">7-day free trial · Cancel anytime</div>
        </div>

        <p className="redline">
          No pay-to-win. No stat boosts. No grind skips. <br />
          Cosmetic, narrative, experiential — never mechanical.
        </p>
      </div>
    </section>
  );
}

// ============================================================
// FAQ
// ============================================================
function FAQ() {
  const items = [
    {
      q: "What do I need to play?",
      a: "A phone and a pair of headphones. The phone is a glanceable HUD; everything else happens out loud."
    },
    {
      q: "Can I play solo, or do I need a group?",
      a: "Both. Solo with your AI companion and the Master, or with a party of up to four — real friends, real voices, in the same scene."
    },
    {
      q: "I'm not great at improv. Will I freeze?",
      a: "The Master gives you space and follows your lead. Say one word or fifty; the world fills in around you. You'll find your voice in the first hour."
    },
    {
      q: "How long is a session?",
      a: "Anywhere from five minutes to ninety. The Master scales the scene to the time you have. Five-minute stops by the campfire count."
    },
    {
      q: "Will the Master remember me?",
      a: "Yes. Your name, your patron, the price you paid the smith three nights ago, the thing your companion said in the rain. The world keeps notes on you between sessions."
    },
    {
      q: "How is this different from an AI chatbot?",
      a: "A chatbot improvises a scene. The Master runs a world — with rules, with consequences, with continuity. There are dice in this. There is a wound at the center."
    },
    {
      q: "Can I play while doing other things?",
      a: "That is most of what this game is for. Walks. Commutes. Long quiet hours. Audio-first means your eyes are free for the dishes."
    },
    {
      q: "When does it launch?",
      a: "Closed playtest waves through 2026, with broader access through 2027. Drop your email below and we'll send a Veil-key when your cohort opens."
    }
  ];
  const [openIdx, setOpenIdx] = React.useState(0);
  return (
    <section className="section" id="faq">
      <div className="container">
        <div className="section-num"><span>08</span> Questions</div>
        <h2 className="section-title">
          What you'll probably ask first.
        </h2>
        <p className="section-lede">
          The Master answers in character, but here are the short versions.
        </p>

        <ul className="faq-list">
          {items.map((it, i) => (
            <li key={i} className={"faq-item" + (openIdx === i ? " open" : "")}>
              <button
                className="faq-q"
                onClick={() => setOpenIdx(openIdx === i ? -1 : i)}
                aria-expanded={openIdx === i}
              >
                <span className="faq-q-num">{String(i + 1).padStart(2, '0')}</span>
                <span className="faq-q-text">{it.q}</span>
                <span className="faq-q-toggle" aria-hidden="true">{openIdx === i ? '−' : '+'}</span>
              </button>
              <div className="faq-a-wrap">
                <p className="faq-a">{it.a}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ============================================================
// Waitlist
// ============================================================
function Waitlist() {
  const [email, setEmail] = React.useState("");
  const [submitted, setSubmitted] = React.useState(false);
  const onSubmit = (e) => {
    e.preventDefault();
    if (!email.includes("@")) return;
    setSubmitted(true);
  };
  return (
    <section className="section" id="waitlist" style={{ paddingTop: 120, paddingBottom: 120 }}>
      <div className="container" style={{ textAlign: 'center' }}>
        <div className="section-num" style={{ justifyContent: 'center' }}><span>09</span> Enter the World</div>
        <h2 className="section-title" style={{ margin: '0 auto 32px', textAlign: 'center', maxWidth: '20ch' }}>
          The trial begins <em>when the seal is broken.</em>
        </h2>
        <p className="section-lede" style={{ margin: '0 auto', textAlign: 'center' }}>
          Closed playtest opens in waves through 2026. Drop your email and we'll send a Veil-key when your cohort opens — no marketing churn, just the keys.
        </p>

        <div className="waitlist-wrap">
          {!submitted ? (
            <>
              <form className="waitlist-form" onSubmit={onSubmit}>
                <input
                  type="email"
                  required
                  placeholder="your.true.name@aethos"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  aria-label="Email"
                />
                <button type="submit">Request Veil-Key →</button>
              </form>
              <div className="waitlist-meta">
                <span>4,287 wanderers on the list</span>
                <span>Next wave · Q3 2026</span>
              </div>
            </>
          ) : (
            <div className="waitlist-success">
              <div className="label">A whisper, received</div>
              <div className="msg">“The gods know your name. Listen for the bell.”</div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

// ============================================================
// Footer
// ============================================================
function Footer() {
  return (
    <footer>
      <div className="container">
        <div className="footer-grid">
          <div className="footer-brand">
            <div className="footer-logo">Divine Ruin</div>
            <p>A voice-first audio RPG set in Aethos, a world thirty years into a war it does not understand.</p>
          </div>
          <div className="footer-col">
            <h4>The Game</h4>
            <ul>
              <li><a href="#world">The World</a></li>
              <li><a href="#pantheon">The Pantheon</a></li>
              <li><a href="#pricing">Subscribe</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Deeper Docs</h4>
            <ul>
              <li><a href="#">Aethos Lore Bible</a></li>
              <li><a href="#">Game Design Doc</a></li>
              <li><a href="#">Technical Architecture</a></li>
              <li><a href="#">Cost Model</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h4>Company</h4>
            <ul>
              <li><a href="#">About</a></li>
              <li><a href="#">Careers</a></li>
              <li><a href="#">Press</a></li>
              <li><a href="#">Contact</a></li>
            </ul>
          </div>
        </div>
        <div className="footer-base">
          <span>© 2026 Divine Ruin Studios</span>
          <span>Crafted in ink &amp; signal</span>
        </div>
      </div>
    </footer>
  );
}

Object.assign(window, { Races, Pantheon, Classes, Tech, Pricing, FAQ, Waitlist, Footer });
