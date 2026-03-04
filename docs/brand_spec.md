# Divine Ruin — Brand & Art Direction Spec

Reference doc for all UI, visual, and art direction decisions. Read this before building any user-facing surface.

---

## Design Tokens

### Colors

```
/* Foundation — near-black surfaces, layered for depth */
--color-void:          #0A0A0B;   /* true background, darkest surface */
--color-ink:           #141417;   /* cards, elevated surfaces, modals */
--color-charcoal:      #1E1E23;   /* borders, dividers, subtle separation */
--color-slate:         #2A2A32;   /* inactive elements, disabled states */

/* Text — warm off-whites, never pure white */
--color-ash:           #6B6B78;   /* secondary text, labels, captions */
--color-bone:          #B8B5AD;   /* primary body text */
--color-parchment:     #D4D0C8;   /* headings, emphasis, high-contrast text */

/* Accent — Hollow teal, the ONLY primary accent */
--color-hollow-faint:  #134E4A;   /* glows, shadows, subtle backgrounds */
--color-hollow-muted:  #1A8A7A;   /* hover states, secondary emphasis */
--color-hollow:        #2DD4BF;   /* primary accent: active states, links, key UI */
--color-hollow-glow:   #5EEAD4;   /* critical alerts, active voice indicator */

/* Semantic — rare, meaning-specific */
--color-ember-faint:   #7C2D12;   /* danger backgrounds */
--color-ember:         #C2410C;   /* damage, HP loss, destructive actions */
--color-divine-faint:  #92702A;   /* god-whisper backgrounds */
--color-divine:        #C9A84C;   /* sacred moments, god contact, rare */
```

**Color ratio rule:** 90% dark foundation / 8% bone-ash text / 2% Hollow accent. Teal means something — active connection, corruption, interaction state. If using it decoratively, you're using too much. Ember and divine gold appear only in their specific game contexts (damage and god-whispers).

### Typography

Three typefaces. No exceptions.

```
/* Display — titles, headings, logo, god-whisper treatments */
--font-display: 'Cormorant Garamond', serif;
/* Weight: 300 (light) default, 400 for subheadings. Never bold. */
/* Tracking: wide (0.1em+). Feels carved, ethereal, might disappear. */

/* Body — narration, descriptions, lore, extended reading */
--font-body: 'Crimson Pro', serif;
/* Weight: 300-400. Warm book typography. Used for DM transcript, */
/* session recaps, lore entries, any prose content. */

/* System — HUD, stats, labels, navigation, timestamps, mechanical UI */
--font-system: 'IBM Plex Mono', monospace;
/* Weight: 300-400. All-caps + wide letter-spacing for labels. */
/* Normal case for data values. Ash color default, teal for active. */
```

Google Fonts import:
```
https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=Crimson+Pro:ital,wght@0,300;0,400;0,600;1,300;1,400&family=IBM+Plex+Mono:wght@300;400&display=swap
```

### Type Scale

| Token | Size | Font | Weight | Use |
|---|---|---|---|---|
| `display` | 48px | Cormorant Garamond | 300 | Logo, hero text |
| `h1` | 28px | Cormorant Garamond | 300 | Screen titles |
| `h2` | 22px | Cormorant Garamond | 400 | Section headings |
| `body-lg` | 18px | Crimson Pro | 300 | DM narration, lore |
| `body` | 15px | Crimson Pro | 400 | General body text |
| `system` | 11px | IBM Plex Mono | 400 | HUD, stats, labels |
| `caption` | 10px | IBM Plex Mono | 300 | Timestamps, metadata |

### Spacing & Radius

```
--radius-sm: 6px;    /* swatches, small cards */
--radius-md: 8px;    /* cards, panels */
--radius-lg: 12px;   /* modals, major containers */
--radius-icon: 27px; /* app icon */

--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-2xl: 48px;
```

### Shadows & Glows

```
/* Hollow glow — for active/connected states */
--glow-hollow: 0 0 20px #134E4A, 0 0 40px #134E4A33;
--glow-hollow-strong: 0 0 8px #2DD4BF, 0 0 20px #134E4A;

/* Hollow text shadow — for logo/display text near Hollow content */
--text-glow-hollow: 0 0 40px #134E4A, 0 0 80px #134E4A;

/* Elevation — subtle, uses ink-charcoal spectrum */
--shadow-card: 0 2px 8px #0A0A0B66;
--shadow-modal: 0 8px 32px #0A0A0BBB;
```

### Grain Overlay

Apply to the root/body element for paper texture across the app:

```css
.grain-overlay {
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: 0.03;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  z-index: 9999;
}
```

---

## UI Patterns

### Surface Hierarchy

1. **Void** (`#0A0A0B`) — app background, deepest layer
2. **Ink** (`#141417`) — cards, panels, elevated surfaces
3. **Charcoal** (`#1E1E23`) — borders, dividers between surfaces
4. **Slate** (`#2A2A32`) — disabled/inactive elements, tertiary content

Never use pure black (`#000000`) or pure white (`#FFFFFF`).

### Text Hierarchy

| Role | Color | Font | Example |
|---|---|---|---|
| Heading | `parchment` | Cormorant Garamond 300 | Screen titles, section names |
| Body | `bone` | Crimson Pro 400 | DM narration, descriptions |
| Secondary | `ash` | IBM Plex Mono 400 | Labels, metadata |
| Inactive | `slate` | IBM Plex Mono 300 | Disabled items, divider values |
| Accent | `hollow` | IBM Plex Mono 400 | Active quest, live indicator, links |
| Danger | `ember` | IBM Plex Mono 400 | HP loss, damage values |
| Sacred | `divine` | Cormorant Garamond 300i | God-whisper text |

### HUD Elements

All HUD uses `font-system` (IBM Plex Mono). Labels are uppercase with `letter-spacing: 2px`. Data values are normal case. Active/important items use `color-hollow`. Structure:

```
GREYVALE · MARKET DISTRICT          ● LIVE     ← location bar (ash text, hollow live dot)
                                                
HP 47/62    LEVEL 4    VEILWARDEN               ← stats bar (ash labels, parchment values)
▸ Find the cartographer                         ← active quest (hollow arrow, bone text)
session 00:12:34 · greyvale                     ← footer (slate text)
```

### Special UI Treatments

**God-whisper notification:**
- Border: `1px solid --color-divine-faint`
- Top edge: horizontal gradient line (`transparent → divine → transparent`, opacity 0.4)
- Text: Cormorant Garamond 300 italic, `color-divine`, opacity 0.9
- Attribution: IBM Plex Mono 9px, `color-divine-faint`, uppercase, `letter-spacing: 3px`

**Hollow corruption alert:**
- Border: `1px solid --color-hollow-faint`
- Background: radial gradient from bottom (`hollow-faint 33% opacity → transparent 70%`)
- Label: IBM Plex Mono 10px, `color-hollow`, uppercase
- Body: Crimson Pro 14px, `color-bone`, opacity 0.8

**Combat damage:**
- Border: `1px solid --color-ember-faint`
- Damage value: IBM Plex Mono, `color-ember`
- HP display: large number in `parchment`, denominator in `slate`
- HP bar: 3px height, `charcoal` track, gradient fill (`ember → parchment`)

**Voice active indicator:**
- 6px circle, `color-hollow`, `box-shadow: 0 0 8px color-hollow`
- "LIVE" label: IBM Plex Mono 10px, `color-hollow`

**Voice waveform:**
- Vertical bars, 3px wide, `color-hollow`, varying heights
- Opacity varies 0.4–0.8 per bar for organic feel

---

## Art Direction

### The Dissolving Style

Every illustration: focal point rendered in confident ink → loose brushwork → scattered marks → bare paper at edges. The art suggests; the DM's voice completes.

**Medium:** Black ink (brush + nib), graphite underdrawing visible at edges.
**Color:** Near-monochrome. Color earned, not applied. Only three accent colors as watercolor washes:
- Teal (`#2DD4BF`) — corruption, supernatural, Hollow. Bleeds beyond ink lines.
- Ember (`#C2410C`) — fire, combat, danger. Contained, warm.
- Gold (`#C9A84C`) — sacred, divine. Rarest. Restrained, almost fragile.

If a scene doesn't call for these, it stays fully monochrome.

**Texture:** Paper grain, ink bleed, splatter marks. Never clean, vector, or digital-smooth.

### Art Categories

| Category | Where | Finish Level | Color |
|---|---|---|---|
| Companion portraits | Party screen, character cards | Most finished — face detailed, edges dissolve | Rarely teal (Hollow scenes only) |
| NPC portraits | Encounters, dialogue | Rough/impressionistic — few strokes, mostly suggested | Almost never |
| Location illustrations | Session bg, loading, location cards | Wide, atmospheric — center defined, edges fade | Context-specific accent |
| Item/object art | Inventory, loot, shop | Technical specimen plate — precise center, clean negative space | Functional (ember for weapons, teal for corrupted) |
| Story moments | Recaps, milestones, achievements | Most finished overall — graphic novel panel feel | Always one accent color |
| Hollow art | Corruption content | Style itself corrupts — wobbling lines, bleeding washes, central void | Teal dominant, stain-like |

### Style Guardrails

**This is Divine Ruin:** ink and brush, dissolving edges, monochrome + earned color, paper texture, atmospheric, figures remembered not photographed, negative space as composition tool.

**This is NOT:** polished digital painting, saturated full-color, anime/manga, pixel art, photorealistic, generic fantasy (glowing swords, dramatic poses), flat vector, art that competes with audio.

---

## Logo

Wordmark: `Cormorant Garamond` weight 300, all-caps, `letter-spacing: 8px+`.

```css
.logo-text {
  font-family: 'Cormorant Garamond', serif;
  font-weight: 300;
  letter-spacing: 8px;
  text-transform: uppercase;
  color: var(--color-parchment);
}
```

App icon: "DR" monogram in Cormorant Garamond 300. Near-black background with subtle radial gradient. Faint teal glow bleeds up from bottom edge. Darkest thing on the home screen.

---

## Brand Principles (Quick Reference)

1. **Audio leads, visuals follow** — UI is dark and quiet, never competing with the DM's voice
2. **Restraint is the aesthetic** — 90/8/2 color ratio is a rule. Every element earns its place
3. **Hollow teal is the only accent** — when it appears, it means something
4. **Imperfection is identity** — ink texture, grain, thin weights, organic feel
5. **Typography carries the weight** — three typefaces creating tension between sacred and raw
6. **Dark means dark** — near-black backgrounds, off-white text, darkest app on the phone
