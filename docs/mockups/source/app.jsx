/* global React, ReactDOM, useTweaks, TweaksPanel, TweakSection, TweakSlider, TweakRadio */
const { useEffect } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "hollow",
  "grain": 0.06,
  "layout": "centered"
}/*EDITMODE-END*/;

// Accent palettes
const ACCENT_MAP = {
  hollow:  { name: "Hollow",  c: "#2DD4BF", muted: "#1A8A7A", faint: "#134E4A", glow: "#5EEAD4" },
  divine:  { name: "Divine",  c: "#C9A84C", muted: "#A88838", faint: "#92702A", glow: "#E5C56A" },
  ember:   { name: "Ember",   c: "#C2410C", muted: "#9A3309", faint: "#7C2D12", glow: "#E5651F" }
};

function applyAccent(key) {
  const a = ACCENT_MAP[key] || ACCENT_MAP.hollow;
  const r = document.documentElement.style;
  r.setProperty('--accent', a.c);
  r.setProperty('--accent-muted', a.muted);
  r.setProperty('--accent-faint', a.faint);
  r.setProperty('--accent-glow', a.glow);
}

function applyGrain(v) {
  document.documentElement.style.setProperty('--grain-opacity', String(v));
}

function useScrollReveal() {
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach(e => {
          if (e.isIntersecting) {
            e.target.classList.add('in');
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );
    document.querySelectorAll('.reveal').forEach(el => io.observe(el));
    return () => io.disconnect();
  }, []);
}

function App() {
  const [t, setT] = useTweaks(TWEAK_DEFAULTS);

  useEffect(() => { applyAccent(t.accent); }, [t.accent]);
  useEffect(() => { applyGrain(t.grain); }, [t.grain]);

  useScrollReveal();

  return (
    <>
      <div className="grain-overlay" />
      <div className="vignette" />

      <NavBar />
      <Hero layout={t.layout} />
      <Premise />
      <Session />
      <World />
      <Races />
      <Pantheon />
      <Classes />
      <Tech />
      <Pricing />
      <FAQ />
      <Waitlist />
      <Footer />

      <TweaksPanel>
        <TweakSection label="Hero">
          <TweakRadio
            label="Layout"
            value={t.layout}
            onChange={v => setT('layout', v)}
            options={[
              { value: 'centered', label: 'Centered' },
              { value: 'split', label: 'Left' },
              { value: 'cinematic', label: 'Cinematic' }
            ]}
          />
        </TweakSection>

        <TweakSection label="Accent">
          <TweakRadio
            label="Color"
            value={t.accent}
            onChange={v => setT('accent', v)}
            options={[
              { value: 'hollow', label: 'Teal' },
              { value: 'divine', label: 'Gold' },
              { value: 'ember', label: 'Ember' }
            ]}
          />
        </TweakSection>

        <TweakSection label="Atmosphere">
          <TweakSlider
            label="Grain"
            value={t.grain}
            min={0} max={0.18} step={0.01}
            onChange={v => setT('grain', v)}
          />
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
