# Homepage mockup — source of truth

Uncompiled source for the Divine Ruin marketing homepage mockup. **This is the
canonical reference** for the `apps/web` marketing-site copy, structure, and
styling (milestones M3–M6). The previously-vendored 2 MB compiled standalone
HTML was removed as a duplicate — this readable source plus `screenshots/`
supersedes it. The original runnable mockup lives with the customer.

| File | What it holds |
|------|---------------|
| `hero.jsx` | NavBar, AudioDemo, Hero (centered + cinematic layouts) — exact copy, structure, class names. |
| `sections-1.jsx` | Premise (§01), Session (§02), World (§03) — copy + structure. |
| `sections-2.jsx` | Peoples (§04), Pantheon (§05), Build (§06), Subscription/Pricing (§07), Questions/FAQ (§08), Enter-the-World/Waitlist (§09), Footer. |
| `app.jsx` | App shell / section ordering. |
| `tweaks-panel.jsx` | A design-time tweak panel — not shipped, ignore for the build. |
| `styles.css` | The full mockup stylesheet (design tokens, layout, animations). |
| `Divine Ruin Homepage (standalone source).html` | The source entry HTML. |
| `screenshots/` | Rendered reference screenshots (hero + section variants). |

## Notes for the apps/web rebuild

- The mockup is a single client-rendered React app. `apps/web` rebuilds it as
  prerendered + hydrated components, hydration-safe, with co-located CSS per
  section and BEM class names (not the mockup's generic `.num`/`.label`/`.desc`).
- The mockup's AudioDemo is a **simulated** player (a fake 30s timer + random
  drifting bars, no real `<audio>`). `apps/web` ships a real lazy-loaded sample
  instead — so our player is more functional than the mockup; only its copy
  (title, time format) should match.
- Lore docs the mockup bundled under `uploads/` already live in the repo `docs/`
  (`aethos_lore.md`, `brand_spec.md`, `game_design_doc.md`, `product_overview.md`).
