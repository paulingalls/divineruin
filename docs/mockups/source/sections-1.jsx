/* global React */
const { useState: useStateS } = React;

// ============================================================
// Premise — "What this is"
// ============================================================
function Premise() {
  const items = [
    {
      num: "01",
      label: "Voice-first",
      desc: "You speak, the world answers. No buttons. No menus. The phone is a glanceable HUD; your voice is the input."
    },
    {
      num: "02",
      label: "Solo or with friends",
      desc: "Play alone with an AI companion, or bring a party of up to four. Real voices in your ear, around a virtual table, anywhere."
    },
    {
      num: "03",
      label: "An AI Dungeon Master, all your own",
      desc: "Personal narrator. Voices every NPC. Adapts to everything you do. Remembers what happened three sessions ago."
    },
    {
      num: "04",
      label: "A persistent mystery",
      desc: "Thirty years ago the Veil shattered. The gods have offered ten different explanations — and the truth is buried in artifacts, contradictions, and pieces of forgotten lore scattered across the world."
    }
  ];
  return (
    <section className="section" id="premise">
      <div className="container">
        <div className="section-num"><span>01</span> The Premise</div>
        <h2 className="section-title">
          Put on headphones. <em>Enter a living world.</em>
        </h2>
        <p className="section-lede">
          Divine Ruin is a voice-first fantasy RPG. Imagine an Audible novel that listens back — every NPC voiced, every scene improvised, every choice yours. Play solo or with a party of up to four, anywhere you can wear headphones.
        </p>

        <ul className="premise-list" style={{ marginTop: 72, maxWidth: '780px' }}>
          {items.map(it => (
            <li key={it.num}>
              <span className="num">{it.num}</span>
              <div>
                <div className="label">{it.label}</div>
                <div className="desc">{it.desc}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ============================================================
// Session — transcript walkthrough
// ============================================================
function Session() {
  const lines = [
    { who: "Narrator", what: "The Accord of Tides at dusk. Waves against the harbor wall. Vendors closing stalls. Somewhere behind you, a lute is tuning itself into a song that should not be familiar.", cls: "" },
    { who: "You", what: "I want to find the blacksmith.", cls: "player" },
    { who: "Narrator", what: "You weave through the market. The forge fire is already banked when you arrive — Halric the smith looks up, recognizes you, and slides the sword across the bench. He remembers you commissioned it three nights ago.", cls: "" },
    { who: "Halric", what: "“Steel sang true. Forty silver, as agreed. And mind the Greyvale — two parties came back today. Only one party.”", cls: "" },
    { who: "You", what: "I pay him and head for the tavern to meet my party.", cls: "player" },
    { who: "Combat", what: "Something moves in the treeline. Three shapes. They do not speak. They do not breathe.", cls: "combat" },
    { who: "Veythar", what: "“Child. The wound in the world widens. Look closer at what you found yesterday — the ledger lied.”", cls: "god" }
  ];
  return (
    <section className="section" id="session" style={{ background: 'linear-gradient(180deg, var(--color-void), #0B0D0E 50%, var(--color-void))' }}>
      <div className="container">
        <div className="section-num"><span>02</span> A Session</div>
        <h2 className="section-title">
          You speak. <em>The world speaks back.</em>
        </h2>
        <p className="section-lede">
          Every word below is generated and voiced in real time. The narrator, the smith, the god — different voices, one continuous scene, in your ear.
        </p>

        <div className="transcript">
          {lines.map((l, i) => (
            <div key={i} className={"transcript-line " + l.cls}>
              <span className="who">{l.who}</span>
              <span className="what">{l.what}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ============================================================
// World — The Hollow, the Sundering, and Aethos
// ============================================================
function World() {
  const timeline = [
    {
      year: "Year −30",
      title: "The Sundering",
      desc: "In a single night, the Veil — the membrane between Aethos and what lies behind it — was torn. The great city of Aelindra unmade itself by dawn. The first Hollow walked at noon."
    },
    {
      year: "Year −28",
      title: "The Five Accords",
      desc: "What was left of civilization gathered at the port of Tides and swore the Accords: shared borders, shared armies, and a careful, public agreement that no one was to blame."
    },
    {
      year: "Year −12",
      title: "The Voidmaw stabilizes",
      desc: "The wound where Aelindra fell stops widening — but begins, on quiet nights, to whisper. Some who listen come back changed. Most do not come back."
    },
    {
      year: "Year −3",
      title: "The Greyvale bends",
      desc: "Forests south of the Maw begin to grow in directions the seasons do not recognize. Birds learn songs no one taught them. A scout returns alone, speaking only in the voices of the others."
    },
    {
      year: "Now",
      title: "The Veil thins again",
      desc: "Patrons stir. Oracles disagree. Something on the far side of the wound has started counting backwards. You arrive in Aethos with a name, a god, and one chance to be useful before the second tearing.",
      now: true
    }
  ];

  const places = [
    {
      name: "Accord of Tides",
      kind: "Port capital",
      status: "Held",
      desc: "The last great city. Built on pylons over a harbor that never freezes. Half marketplace, half military barracks, all rumor."
    },
    {
      name: "The Voidmaw",
      kind: "The wound",
      status: "Lost",
      desc: "Where Aelindra was. A spiral of nothing, a mile across, that the maps refuse to settle on. The closer you stand, the older you feel."
    },
    {
      name: "The Greyvale",
      kind: "Corrupted wildland",
      status: "Bending",
      desc: "A forest belt south of the Maw, leaning slowly inward. Trees with the wrong number of branches. Useful, if you're brave, and bring witnesses."
    },
    {
      name: "Ashen Reach",
      kind: "Mountain frontier",
      status: "Held, barely",
      desc: "Northern peaks. The old dwarven holds, now garrisons. The wind there carries arguments from a thousand years ago."
    },
    {
      name: "The Hollow Marches",
      kind: "Frontier line",
      status: "Contested",
      desc: "The ring of forts and waystations where the Hollow is held, by spear and prayer and the patience of the Ironhand."
    },
    {
      name: "Silent Library",
      kind: "Order seat",
      status: "Held",
      desc: "Veythar's keep. Every book ever written. Most of them lying about the same thirty days, thirty years ago."
    }
  ];

  const statusColor = (s) => {
    if (s === "Lost") return "var(--color-ember)";
    if (s === "Bending" || s === "Contested" || s === "Held, barely") return "var(--color-divine)";
    return "var(--accent)";
  };

  return (
    <section className="section" id="world">
      <div className="container">
        <div className="section-num"><span>03</span> The World</div>
        <h2 className="section-title">
          Aethos, <em>and the wound at its center.</em>
        </h2>
        <p className="section-lede">
          Ten gods tend a fantasy world that is running out of time. Thirty years ago the Veil shattered. The fallen city of Aelindra is now a wound in reality called the Voidmaw. Through it pours the Hollow — and the gods cannot agree on what the Hollow is.
        </p>

        <div className="hollow-alert">
          <div className="label">Hollow corruption detected</div>
          <div className="body">
            They do not speak. They do not negotiate. They consume. <em>Where they come from, and how they found their way through, no living thing in Aethos can agree.</em>
          </div>
        </div>

        {/* Atmospheric quote pull */}
        <figure className="quote-pull">
          <blockquote>
            We don't say the names of the lost out loud anymore. The Hollow listens for names.
          </blockquote>
          <figcaption>
            <span className="who">A wall at the southern gate of the Ashmark</span>
            <span className="when">scratched, undated</span>
          </figcaption>
        </figure>

        {/* Timeline */}
        <div className="lore-block">
          <div className="lore-eyebrow">The Sundering — a record</div>
          <ol className="timeline">
            {timeline.map((t, i) => (
              <li key={i} className={"tl-event" + (t.now ? " tl-now" : "")}>
                <div className="tl-year">{t.year}</div>
                <div className="tl-marker" aria-hidden="true" />
                <div className="tl-content">
                  <h3 className="tl-title">{t.title}</h3>
                  <p className="tl-desc">{t.desc}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* Places */}
        <div className="lore-block">
          <div className="lore-eyebrow">Where the world holds, and where it doesn't</div>
          <div className="places-grid">
            {places.map(p => (
              <article className="place" key={p.name}>
                <div className="place-head">
                  <span className="place-kind">{p.kind}</span>
                  <span className="place-status" style={{ color: statusColor(p.status) }}>
                    <span className="place-dot" style={{ background: statusColor(p.status), boxShadow: `0 0 6px ${statusColor(p.status)}` }} />
                    {p.status}
                  </span>
                </div>
                <h3 className="place-name">{p.name}</h3>
                <p className="place-desc">{p.desc}</p>
              </article>
            ))}
          </div>
        </div>

        {/* Hollow taxonomy — field notes from the Ashmark */}
        <div className="lore-block field-notes">
          <div className="lore-eyebrow">A field guide, copied without permission from an Ashmark wardroom</div>
          <ol className="taxonomy">
            <li className="tx tx-1">
              <div className="tx-meta">
                <span className="tx-tier">Tier I</span>
                <span className="tx-threat">Common · Low threat</span>
              </div>
              <h3 className="tx-name">Drift</h3>
              <p className="tx-desc">They move the way leaves move across pavement. No purpose, no direction. The pavement remembers them anyway.</p>
              <p className="tx-quote">“If the moths find you, walk. Don't run — they feed on panic. Walk fast, and get indoors.”</p>
            </li>
            <li className="tx tx-2">
              <div className="tx-meta">
                <span className="tx-tier">Tier II</span>
                <span className="tx-threat">Uncommon · Moderate</span>
              </div>
              <h3 className="tx-name">Rend</h3>
              <p className="tx-desc">Coherent enough to want. Coherent enough to wait. They arrange the room around you before they ever touch you.</p>
              <p className="tx-quote">“When the room doesn't sound right, stop walking. Finding the weaver before it finishes is the only thing that matters.”</p>
            </li>
            <li className="tx tx-3">
              <div className="tx-meta">
                <span className="tx-tier">Tier III</span>
                <span className="tx-threat">Rare · High</span>
              </div>
              <h3 className="tx-name">Wrack</h3>
              <p className="tx-desc">Each sighting is reported singly. They have weight in the world the way mountains do. They are still arriving.</p>
              <p className="tx-quote">“When your own voice stops sounding like you, fall back. You're inside its reach.”</p>
            </li>
            <li className="tx tx-4">
              <div className="tx-meta">
                <span className="tx-tier">Tier IV</span>
                <span className="tx-threat">Singular · Extreme</span>
              </div>
              <h3 className="tx-name">The Named</h3>
              <p className="tx-desc">There are not many. The Ashmark companies report them by name, the way you report a storm. Most live near the rim of the Voidmaw. They have not yet been provoked.</p>
              <p className="tx-quote tx-quote-redacted">[ this passage has been crossed out ]</p>
            </li>
          </ol>
        </div>

        <dl className="world-meta">
          <div>
            <dt>The Setting</dt>
            <dd>Aethos<span className="small">A continent. Ten gods. Five surviving civilizations.</span></dd>
          </div>
          <div>
            <dt>The Threat</dt>
            <dd>The Hollow<span className="small">Spreading from the Voidmaw, southward, every game-tick.</span></dd>
          </div>
          <div>
            <dt>The Mystery</dt>
            <dd>What tore the Veil?<span className="small">Buried in artifacts, contradictions, and forgotten lore.</span></dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

Object.assign(window, { Premise, Session, World });
