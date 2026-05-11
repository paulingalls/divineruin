# Divine Ruin — Image Generation Prompt Library
## For Nano Banana 2 (Gemini 3.1 Flash Image)

---

## Style Foundation

Every prompt builds on a shared style DNA. This base description should be adapted per category but never abandoned:

**Core style keywords:** ink wash illustration, partially unfinished, dissolving edges, visible brushwork, paper texture, monochrome with selective color accent, dark fantasy, atmospheric, hand-drawn feel, fine art quality

**What to always include:**
- Medium: ink wash / brush ink / ink and graphite
- Finish level: partially unfinished, edges dissolving into raw sketch marks
- Texture: aged paper texture, visible grain, ink bleed
- Background: dark, near-black (`#0A0A0B` to `#141417`)
- Color rule: near-monochrome with ONE selective color wash when appropriate
- Mood: atmospheric, intimate, slightly melancholic

**What to avoid in prompts:**
- "digital art", "digital painting", "3D render", "concept art" (too polished)
- "vibrant colors", "colorful", "bright" (breaks the desaturated palette)
- "detailed background" (backgrounds should dissolve, not compete)
- "anime", "cartoon", "pixel art", "vector" (wrong aesthetic entirely)
- "photorealistic", "hyperrealistic" (uncanny, not atmospheric)

---

## Accent Color Rules

Only three colors ever appear in the art. Specify them precisely:

| Color | Hex | When to use | Prompt language |
|---|---|---|---|
| Hollow Teal | `#2DD4BF` | Corruption, supernatural, the Hollow | "selective teal wash", "teal ink bleed", "cyan-teal watercolor stain" |
| Ember | `#C2410C` | Fire, forges, combat, danger | "warm ember-orange wash", "burnt orange glow", "faint firelight" |
| Divine Gold | `#C9A84C` | Sacred spaces, gods, divine artifacts | "faint gold leaf accent", "pale gold light", "golden aureole" |

If a scene doesn't call for any of these, keep it fully monochrome. Most art should be black ink on dark/aged paper with no color at all.

---

## Category 1: Character Portraits

### Companion Portrait — Primary (most finished)

**Use:** Character card, party screen, companion detail view

```
Ink wash portrait of a young male ranger on a dark near-black background.
Bust composition, three-quarter view facing slightly left. His face and
eyes are rendered in confident ink brushwork with careful detail — sharp
jawline, watchful expression, a thin scar across the bridge of his nose.
Hair is loosely rendered in gestural ink strokes. Shoulders and collar of
a leather traveling cloak dissolve into scattered ink marks and raw
graphite sketch lines at the edges. The lower portion of the portrait
fades into bare aged paper texture. Monochrome — black ink and graphite
on dark cream paper. No color. Partially unfinished, with the dissolving
edges suggesting the figure is being remembered rather than observed.
Fine art quality, visible brushwork, hand-drawn feel. Aspect ratio 3:4.
```

### Companion Portrait — Variant (concerned/alert)

```
Ink wash portrait of a young male ranger, three-quarter bust view, on
dark near-black background. Expression is tense and alert — brow
furrowed, jaw set, eyes scanning. Rendered in confident ink brushwork
at the face, dissolving into loose gestural strokes at the shoulders
and scattered ink marks at the edges. Thin scar across nose bridge.
Hair rendered in quick, energetic brush strokes suggesting wind.
A faint teal watercolor wash bleeds subtly across one side of his
jaw — barely visible, like a stain spreading. Aged paper texture,
ink bleed at stroke edges. Mostly monochrome with only that subtle
teal accent. Partially unfinished, atmospheric. Aspect ratio 3:4.
```

### NPC Portrait — Brief Encounter (rougher, more impressionistic)

```
Loose ink sketch portrait of an elderly female merchant on a dark
background. Minimal rendering — just enough to capture a broad face,
deep-set knowing eyes, and a hooded wool shawl. Most of the figure
is suggested through a few confident brush strokes rather than
detailed rendering. Edges dissolve almost immediately into scattered
ink marks and bare paper. Monochrome — black ink on aged dark paper.
The impression of a face glimpsed briefly by firelight. No color
accents. Raw, gestural, unfinished. Fine art quality despite the
minimal rendering. Aspect ratio 1:1.
```

### Player Character — Creation Screen

```
Ink wash portrait of a [class] character on dark near-black background.
Front-facing bust composition. The face is the focal point — rendered
with detailed ink brushwork showing [key feature: e.g., braided hair,
ritual scars, soft features]. Expression is neutral but present, as if
meeting the viewer's gaze for the first time. Below the collarbone, the
figure dissolves rapidly into loose brushwork, then scattered marks,
then bare paper. Monochrome — black ink and graphite on dark cream
paper. No background detail. The character emerges from darkness and
fades back into it. Partially unfinished. Fine art quality, visible
brush strokes, hand-drawn feel. Aspect ratio 3:4.
```

**Template variables:** Replace `[class]` and `[key feature]` per character. Keep everything else constant for visual consistency across the creation flow.

---

## Category 2: Location Illustrations

### Town / Settlement

**Use:** Session background, loading screen, location card

```
Wide ink wash illustration of a small medieval town nestled in a river
valley at dusk. The central cluster of buildings — a stone bridge, a
tavern with a lit doorway, a church spire — is rendered in confident
ink brushwork with architectural detail. Surrounding buildings become
increasingly gestural and loose. The hillsides and sky dissolve into
broad ink washes and scattered marks, fading to bare dark paper at the
edges. A faint ember-orange watercolor wash glows from the tavern
windows and a few street lanterns — the only color in the image. The
rest is monochrome ink on dark aged paper. Atmospheric, moody, like a
traveler's field sketch made in fading light. Visible brushwork, ink
bleed, paper grain texture. Aspect ratio 16:9.
```

### Wilderness / Forest

```
Ink wash landscape of a dense old-growth forest, dark and atmospheric.
The nearest trees are rendered in bold ink strokes — thick trunks,
textured bark, overhanging branches. Trees recede into increasingly
loose washes, becoming silhouettes, then faint ink marks, then bare
dark paper. A narrow path winds between the roots, suggested by a few
confident lines. No color — entirely monochrome black ink on dark paper.
Dappled light implied by areas of lighter wash, not bright highlights.
The mood is quiet and ancient, not threatening. Visible brushwork, paper
texture, some areas left as raw graphite underdrawing showing through.
Partially unfinished. Aspect ratio 16:9.
```

### Corrupted / Hollow Location

```
Ink wash illustration of a ruined stone temple overtaken by an unnatural
force. The architecture is rendered in detailed ink work — crumbling
columns, a fractured altar, fallen masonry — but the ink lines begin
to distort and wobble in areas of corruption. Washes bleed where they
shouldn't. A prominent teal watercolor stain spreads from the center
of the composition outward, as if the color itself is a corruption —
bleeding beyond the ink lines, pooling in cracks. The edges of the
image dissolve into darkness and scattered marks. The teal is the only
color. The rest is monochrome ink on near-black paper. The illustration
itself looks like it's being consumed by the same force it depicts.
Deeply atmospheric, unsettling. Fine art quality. Aspect ratio 16:9.
```

### Interior — Tavern / Safe Space

```
Ink wash interior of a medieval tavern, seen from a seat by the hearth.
A stone fireplace dominates the center-right, rendered in warm ink detail.
Wooden beams overhead, rough plaster walls. A few figures at tables are
suggested loosely — shapes and postures rather than faces. The far wall
dissolves into shadow and bare paper. Selective ember-orange watercolor
wash radiates from the fireplace — warm, contained, the only color.
Everything beyond the fire's glow is cool monochrome ink. The mood is
safe, intimate, a pause between dangers. Ink bleed at edges, paper
texture, visible brushwork. Partially unfinished. Aspect ratio 16:9.
```

---

## Category 3: Item & Object Art

### Weapon

**Use:** Inventory, loot notification, item detail

```
Technical ink drawing of a single longsword on a plain dark background,
centered with generous negative space around it. Rendered in fine nib
ink — clean, precise linework showing the fuller, crossguard detail,
leather-wrapped grip, and pommel. The blade catches a faint ember-orange
highlight along one edge — a thin line of watercolor suggesting forge
heat. Otherwise entirely monochrome. The style resembles a naturalist's
specimen plate — the object studied and documented with care. No
background detail, no hand holding it. Aged paper texture visible
in the negative space. Fine art quality, meticulous. Aspect ratio 1:1.
```

### Corrupted Artifact

```
Technical ink drawing of an ancient amulet on a dark background, centered.
Fine ink linework renders the chain links and pendant — an eye-shaped
stone in a tarnished silver setting. The linework near the stone begins
to wobble and double, as if the artist's hand was unsteady. A teal
watercolor stain bleeds outward from the stone, spreading beyond the
ink lines into the surrounding paper. The stain looks accidental but
deliberate. The rest of the drawing is monochrome and precise. The
contrast between the controlled linework and the spreading teal creates
unease. Specimen plate style. Aspect ratio 1:1.
```

### Quest Item

```
Technical ink drawing of an old rolled parchment map, partially unfurled,
on a dark background. Fine nib ink renders the curling edges, the faded
markings visible on the exposed surface, and a wax seal holding it
partially closed. Entirely monochrome — no color accents. Precise,
detailed linework for the main object, with faint graphite sketch marks
around the edges suggesting the artist's planning. Clean negative space.
Naturalist specimen style. Aged paper texture. Aspect ratio 1:1.
```

---

## Category 4: Story Moment Illustrations

### Key Narrative Beat — Combat

**Use:** Session recap, achievement unlock, story milestone

```
Dramatic ink wash illustration of a cloaked figure mid-swing with a
longsword against a monstrous shadow. The figure is rendered in bold,
energetic ink strokes — weight, motion, intensity captured in the
brushwork. The monster is less defined — a mass of dark wash and
jagged marks suggesting size and threat without clear anatomy. Ember-
orange watercolor wash flares from the point of impact — sparks, heat,
violence. The color bleeds into the surrounding ink. The background
is pure darkness. The composition is tight and diagonal, like a graphic
novel panel. Edges dissolve, but the central action is rendered with
full intensity. Fine art quality, raw energy. Aspect ratio 2:3.
```

### Key Narrative Beat — God Contact

```
Ink wash illustration of a solitary figure kneeling in a vast empty
space, looking upward. The figure is small in the composition —
rendered in careful ink detail but dwarfed by negative space above.
From above, a single shaft of pale golden light descends — the only
color, applied as a delicate gold watercolor wash that barely touches
the figure's upturned face. The gold is restrained, almost fragile.
The surrounding space is deep black ink wash. The mood is awe, solitude,
the weight of something sacred. Mostly negative space. Partially
unfinished — the figure's lower half dissolves into scattered marks.
Fine art quality, contemplative. Aspect ratio 2:3.
```

### Key Narrative Beat — Hollow Encounter

```
Ink wash illustration of a figure standing at the threshold of a doorway
into wrongness. The figure is seen from behind — rendered in solid ink
work, grounded, human. Beyond the doorway, the illustration itself
breaks down. Ink lines wobble, double, and fragment. Washes bleed in
unnatural directions. A deep teal watercolor stain dominates the space
beyond the door — not illuminating anything, just present, spreading.
The center of the space beyond the door is void — pure empty paper
where something should be but isn't. The contrast between the solid
figure and the corrupted space beyond is the entire composition. The
art style itself is being consumed. Fine art quality, deeply unsettling.
Aspect ratio 2:3.
```

---

## Category 5: UI & Marketing Assets

### App Store Screenshot Background

```
Abstract ink wash composition on near-black background. Sweeping
horizontal brush strokes in varying ink densities create atmospheric
layers — like fog banks or geological strata. Entirely monochrome.
No recognizable subject — pure atmosphere and texture. Some areas of
fine ink splatter. Paper grain visible throughout. The composition
should feel vast and empty, like standing at the edge of an abyss.
Suitable as a background behind overlaid UI text. Fine art quality.
Aspect ratio 9:16.
```

### Social Media — Teaser Image

```
Ink wash close-up of a single human eye on a dark background. The eye
is rendered in exquisite detail — iris texture, reflected light,
individual lashes. But the surrounding face dissolves immediately into
loose ink marks and bare paper. Just the eye exists in full detail.
A faint teal watercolor wash reflects in the iris — a hint of something
the eye is seeing. The rest is monochrome. Intimate, unsettling,
beautiful. The partially unfinished quality makes it feel like a memory
of looking at something terrible. Fine art quality. Aspect ratio 1:1.
```

### Loading Screen — Abstract

```
Minimal ink composition on near-black background. A single vertical
ink wash stroke, broad and gestural, rises from the bottom center. It
begins as dense black ink and fades to nearly nothing at the top —
dissolving into scattered marks and bare paper. The stroke has visible
brush texture, ink bleed, and slight wobble. No other elements. No
color. The composition is almost entirely negative space — a single
mark in darkness. Meditative, atmospheric. Fine art quality.
Aspect ratio 9:16.
```

---

## Consistency Tips for Nano Banana 2

### Maintaining Style Across Assets

1. **Always start with the medium:** "Ink wash illustration" or "ink drawing" — this anchors the model in traditional media, not digital
2. **Specify the paper:** "dark aged paper", "near-black background with paper texture" — prevents clean digital backgrounds
3. **Describe the dissolve explicitly:** "edges dissolve into scattered ink marks and bare paper" — don't assume the model will do this unprompted
4. **Name the color precisely:** "teal watercolor wash" not "blue-green glow" — watercolor language keeps it in the traditional media space
5. **Include imperfection:** "ink bleed", "visible brushwork", "graphite underdrawing showing through" — these details prevent sterile output
6. **End with quality and finish:** "Fine art quality, partially unfinished" — this pairing is important, it tells the model the incompleteness is intentional and skilled

### Aspect Ratios by Asset Type

| Asset | Ratio | Orientation | Notes |
|---|---|---|---|
| Character portrait | 3:4 | Portrait | Bust/three-quarter, dark bg |
| Location illustration | 16:9 | Landscape | Wide, atmospheric |
| Item/object art | 1:1 | Square | Centered, negative space |
| Story moment | 2:3 | Portrait | Dramatic, graphic novel panel |
| Session background | 9:16 | Portrait (mobile) | Atmospheric, behind HUD |
| Marketing/social | 1:1 or 9:16 | Varies | Platform-dependent |

### Iterating on Results

When a generation is close but not right:
- **Too finished/polished:** Add "raw", "unfinished", "sketch-like edges", "artist's underdrawing visible"
- **Too bright/colorful:** Add "near-monochrome", "desaturated", "dark atmosphere", remove any color references
- **Color too prominent:** Specify "faint" or "subtle" before the color wash, add "the color is barely visible, like a stain"
- **Background too busy:** Add "negative space dominant", "minimal background", "dark empty space"
- **Wrong medium feel:** Strengthen "traditional ink", "hand-drawn", "brush and nib", avoid any digital language
- **Too symmetrical/posed:** Add "gestural", "captured mid-motion", "natural posture"
- **Edges too sharp:** Add "dissolving edges", "fading to scattered marks", "unfinished periphery"

---

## Production Pipeline Notes

### Batch Consistency

For assets that need to feel like a set (all companion portraits, all location cards), generate them in the same session if possible. Nano Banana 2's character consistency features help maintain identity across generations. For companions specifically, establish a "reference generation" first, then use image-to-image editing for expression variants and angle changes.

### Post-Processing

Nano Banana 2 output may need light post-processing to fully match the brand:
- **Darken backgrounds** to true near-black (#0A0A0B) if the model generates lighter paper
- **Desaturate slightly** if colors are more vivid than the brand palette allows
- **Add paper grain overlay** if the texture isn't prominent enough
- **Crop to brand aspect ratios** — the model may not always hit exact ratios
- **Color-correct accent washes** to match exact hex values (#2DD4BF, #C2410C, #C9A84C)

### Asset Priority for MVP

Generate in this order (highest priority first):
1. Companion portraits (Kael + other companions) — seen every session
2. Greyvale location illustrations — the MVP arc setting
3. Loading screen abstracts — seen every app open
4. App icon / logo treatments — needed for app store
5. Key story moment illustrations for sessions 1-4
6. Item art for major quest items and weapons
7. NPC portraits for recurring Greyvale characters
8. Marketing assets for app store screenshots and social
