/* global React */
const { useState, useEffect, useRef } = React;

// ============================================================
// NavBar
// ============================================================
function NavBar() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return (
    <nav className={"nav" + (scrolled ? " scrolled" : "")}>
      <div className="container nav-inner">
        <div className="logo">Divine Ruin</div>
        <ul className="nav-links">
          <li><a href="#world">WORLD</a></li>
          <li><a href="#pantheon">PANTHEON</a></li>
          <li><a href="#faq">Questions</a></li>
          <li><a href="#pricing">Subscribe</a></li>
        </ul>
        <a href="#waitlist" className="btn btn-accent">
          <span className="__longlabel" style={{ lineHeight: "1" }}>Request Early Access</span>
          <span className="__shortlabel" style={{ display: 'none' }}>Early Access</span>
        </a>
      </div>
    </nav>);

}

// ============================================================
// Audio Demo
// ============================================================
function AudioDemo() {
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const BAR_COUNT = 48;
  const heights = useRef(
    Array.from({ length: BAR_COUNT }, () => 4 + Math.random() * 18)
  );

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setProgress((p) => {
        if (p >= 1) {setPlaying(false);return 0;}
        return p + 0.004;
      });
    }, 80);
    return () => clearInterval(id);
  }, [playing]);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      heights.current = heights.current.map((h) => {
        const drift = (Math.random() - 0.5) * 6;
        return Math.max(3, Math.min(22, h + drift));
      });
    }, 120);
    return () => clearInterval(id);
  }, [playing]);

  const activeIdx = Math.floor(progress * BAR_COUNT);
  const mm = String(Math.floor(progress * 30)).padStart(2, '0');
  const ss = String(Math.floor(progress * 30 * 60 % 60)).padStart(2, '0');

  return (
    <div className={"audio-demo" + (playing ? " playing" : "")}>
      <button
        className="play-btn"
        onClick={() => setPlaying((p) => !p)}
        aria-label={playing ? "Pause sample" : "Play sample"}>
        
        {playing ?
        <svg viewBox="0 0 14 14" fill="currentColor">
            <rect x="2" y="1" width="3.5" height="12" />
            <rect x="8.5" y="1" width="3.5" height="12" />
          </svg> :

        <svg viewBox="0 0 14 14" fill="currentColor">
            <path d="M2 1 L13 7 L2 13 Z" />
          </svg>
        }
      </button>
      <div className="audio-info">
        <div className="audio-label">
          <span className="title">Hear a session — “The Greyvale Road”</span>
          <span className="time">00:{mm}:{ss} / 00:00:30</span>
        </div>
        <div className="waveform" aria-hidden="true">
          {heights.current.map((h, i) => {
            const isPast = i < activeIdx;
            const isPeak = i === activeIdx - 1 && playing;
            return (
              <div
                key={i}
                className={"bar" + (isPast ? " active" : "") + (isPeak ? " peak" : "")}
                style={{ height: h + "px", opacity: 0.4 + h / 22 * 0.4 }} />);


          })}
        </div>
      </div>
    </div>);

}

// ============================================================
// Hero — three layouts: centered, split (left-aligned), cinematic
// ============================================================
function Hero({ layout }) {
  const pitch = "A fantasy RPG you play with your voice. A world tended by ten gods, threatened by something that should not exist, and narrated to you — in real time — by an AI Dungeon Master who voices every character, remembers every choice, and never reads from a script.";

  if (layout === "cinematic") {
    return <HeroCinematic />;
  }

  return (
    <header className="hero" data-layout={layout} id="top">
      <div className="container">
        <div className="hero-top-meta">
          <div className="left">
            <span className="t-mono">▸ Aethos · Year 30 of the Sundered Veil</span>
          </div>
          <div className="right" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="live-dot" />
            <span className="t-mono">Pre-alpha · Closed playtest</span>
          </div>
        </div>

        <div className="hero-content">
          <h1 className="hero-headline">
            Divine<br /><em>Ruin</em>
          </h1>
          <div className="hero-subhead">the sundered veil</div>
          <p className="hero-pitch">{pitch}</p>

          <div className="hero-cta-row">
            <a href="#waitlist" className="btn btn-accent">
              Request Early Access
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor">
                <path d="M1 5 L9 5 M5 1 L9 5 L5 9" strokeWidth="1.2" />
              </svg>
            </a>
            <a href="#world" className="btn btn-ghost">Enter Aethos ↓</a>
          </div>

          <AudioDemo />
        </div>

        <div className="hero-bottom-meta">
          <div>
            <div className="t-mono-sm" style={{ marginBottom: 6 }}>A voice-first audio RPG</div>
            <div className="t-mono" style={{ color: 'var(--color-bone)', letterSpacing: '0.15em' }}>
              Headphones recommended
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="t-mono-sm" style={{ marginBottom: 6 }}>Scroll</div>
            <div style={{ color: 'var(--accent)', fontFamily: 'var(--font-system)', fontSize: 15, letterSpacing: '0.3em' }}>↓ ↓ ↓</div>
          </div>
        </div>
      </div>
    </header>);

}

// ============================================================
// HeroCinematic — companion-led, audiobook excerpt feel
// ============================================================
function HeroCinematic() {
  return (
    <header className="hero hero-cinematic" data-layout="cinematic" id="top">
      <div className="container">
        <div className="hero-top-meta">
          <div className="left">
            <span className="t-mono">▸ A voice in the dark · Year 30</span>
          </div>
          <div className="right" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="live-dot" />
            <span className="t-mono">Pre-alpha · Closed playtest</span>
          </div>
        </div>

        <div className="cine-stage">
          <div className="cine-meta">
            <div className="t-mono-sm">An excerpt — Session 04 · The Greyvale road</div>
          </div>

          <blockquote className="cine-prose">
            <p>
              <span className="dropcap">S</span>able curls beside you in the firelight. Somewhere above, an owl that does not quite sound like an owl is calling for something that is not quite its mate.
            </p>
            <p>
              <em>“You're awake,”</em> says the Master, in your ear. <em>“The road south is still there. So is what found us last night. Which would you like to discuss first?”</em>
            </p>
          </blockquote>

          <div className="cine-logo-row">
            <div className="cine-logo">Divine Ruin</div>
            <div className="cine-sub">the sundered veil</div>
          </div>

          <div className="cine-pitch">
            A fantasy RPG you play with your voice. The Master listens. The world remembers. Nothing on your screen will tell you what to do next.
          </div>

          <div className="hero-cta-row">
            <a href="#waitlist" className="btn btn-accent">
              Request Early Access
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor">
                <path d="M1 5 L9 5 M5 1 L9 5 L5 9" strokeWidth="1.2" />
              </svg>
            </a>
            <a href="#world" className="btn btn-ghost">Enter Aethos ↓</a>
          </div>

          <AudioDemo />
        </div>

        <div className="hero-bottom-meta">
          <div>
            <div className="t-mono-sm" style={{ marginBottom: 6 }}>A voice-first audio RPG</div>
            <div className="t-mono" style={{ color: 'var(--color-bone)', letterSpacing: '0.15em' }}>
              Headphones strongly recommended
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="t-mono-sm" style={{ marginBottom: 6 }}>Scroll</div>
            <div style={{ color: 'var(--accent)', fontFamily: 'var(--font-system)', fontSize: 15, letterSpacing: '0.3em' }}>↓ ↓ ↓</div>
          </div>
        </div>
      </div>
    </header>);

}

Object.assign(window, { NavBar, Hero, AudioDemo });