// Image prompt templates from docs/image_prompt_library.md
// Pure data + resolver. No side effects.

export type AccentColor = "hollow_teal" | "ember" | "divine_gold" | "none";
export type AspectRatio = "3:4" | "16:9" | "1:1" | "2:3" | "9:16";
export type TemplateCategory =
  | "companion_portrait"
  | "npc_portrait"
  | "player_portrait"
  | "location"
  | "item"
  | "story_moment"
  | "ui";

export interface ImagePromptTemplate {
  id: string;
  category: TemplateCategory;
  name: string;
  promptText: string;
  variableSlots: string[];
  aspectRatio: AspectRatio;
  accentColor: AccentColor;
  accentHex: string | null;
}

const ACCENT_HEX: Record<AccentColor, string | null> = {
  hollow_teal: "#2DD4BF",
  ember: "#C2410C",
  divine_gold: "#C9A84C",
  none: null,
};

export const PROMPT_TEMPLATES: Record<string, ImagePromptTemplate> = {
  companion_portrait_primary: {
    id: "companion_portrait_primary",
    category: "companion_portrait",
    name: "Companion Portrait — Primary",
    promptText: `Ink wash portrait of a young male ranger on a dark near-black background. Bust composition, three-quarter view facing slightly left. His face and eyes are rendered in confident ink brushwork with careful detail — sharp jawline, watchful expression, a thin scar across the bridge of his nose. Hair is loosely rendered in gestural ink strokes. Shoulders and collar of a leather traveling cloak dissolve into scattered ink marks and raw graphite sketch lines at the edges. The lower portion of the portrait fades into bare aged paper texture. Monochrome — black ink and graphite on dark cream paper. No color. Partially unfinished, with the dissolving edges suggesting the figure is being remembered rather than observed. Fine art quality, visible brushwork, hand-drawn feel. Aspect ratio 3:4.`,
    variableSlots: [],
    aspectRatio: "3:4",
    accentColor: "none",
    accentHex: null,
  },

  companion_portrait_alert: {
    id: "companion_portrait_alert",
    category: "companion_portrait",
    name: "Companion Portrait — Alert Variant",
    promptText: `Ink wash portrait of a young male ranger, three-quarter bust view, on dark near-black background. Expression is tense and alert — brow furrowed, jaw set, eyes scanning. Rendered in confident ink brushwork at the face, dissolving into loose gestural strokes at the shoulders and scattered ink marks at the edges. Thin scar across nose bridge. Hair rendered in quick, energetic brush strokes suggesting wind. A faint teal watercolor wash bleeds subtly across one side of his jaw — barely visible, like a stain spreading. Aged paper texture, ink bleed at stroke edges. Mostly monochrome with only that subtle teal accent. Partially unfinished, atmospheric. Aspect ratio 3:4.`,
    variableSlots: [],
    aspectRatio: "3:4",
    accentColor: "hollow_teal",
    accentHex: ACCENT_HEX.hollow_teal,
  },

  npc_portrait: {
    id: "npc_portrait",
    category: "npc_portrait",
    name: "NPC Portrait — Brief Encounter",
    promptText: `Loose ink sketch portrait of {{description}} on a dark background. Minimal rendering — just enough to capture {{features}}. Most of the figure is suggested through a few confident brush strokes rather than detailed rendering. Edges dissolve almost immediately into scattered ink marks and bare paper. Monochrome — black ink on aged dark paper. The impression of a face glimpsed briefly by firelight. No color accents. Raw, gestural, unfinished. Fine art quality despite the minimal rendering. Aspect ratio 1:1.`,
    variableSlots: ["description", "features"],
    aspectRatio: "1:1",
    accentColor: "none",
    accentHex: null,
  },

  player_character_creation: {
    id: "player_character_creation",
    category: "player_portrait",
    name: "Player Character — Creation Screen",
    promptText: `Ink wash portrait of a {{class}} character on dark near-black background. Front-facing bust composition. The face is the focal point — rendered with detailed ink brushwork showing {{key_feature}}. Expression is neutral but present, as if meeting the viewer's gaze for the first time. Below the collarbone, the figure dissolves rapidly into loose brushwork, then scattered marks, then bare paper. Monochrome — black ink and graphite on dark cream paper. No background detail. The character emerges from darkness and fades back into it. Partially unfinished. Fine art quality, visible brush strokes, hand-drawn feel. Aspect ratio 3:4.`,
    variableSlots: ["class", "key_feature"],
    aspectRatio: "3:4",
    accentColor: "none",
    accentHex: null,
  },

  location_town: {
    id: "location_town",
    category: "location",
    name: "Town / Settlement",
    promptText: `Wide ink wash illustration of {{location_name}}, a small medieval town nestled in a river valley at dusk. The central cluster of buildings — a stone bridge, a tavern with a lit doorway, a church spire — is rendered in confident ink brushwork with architectural detail. Surrounding buildings become increasingly gestural and loose. The hillsides and sky dissolve into broad ink washes and scattered marks, fading to bare dark paper at the edges. A faint ember-orange watercolor wash glows from the tavern windows and a few street lanterns — the only color in the image. The rest is monochrome ink on dark aged paper. Atmospheric, moody, like a traveler's field sketch made in fading light. Visible brushwork, ink bleed, paper grain texture. Aspect ratio 16:9.`,
    variableSlots: ["location_name"],
    aspectRatio: "16:9",
    accentColor: "ember",
    accentHex: ACCENT_HEX.ember,
  },

  location_wilderness: {
    id: "location_wilderness",
    category: "location",
    name: "Wilderness / Forest",
    promptText: `Ink wash landscape of {{location_name}}, a dense old-growth forest, dark and atmospheric. The nearest trees are rendered in bold ink strokes — thick trunks, textured bark, overhanging branches. Trees recede into increasingly loose washes, becoming silhouettes, then faint ink marks, then bare dark paper. A narrow path winds between the roots, suggested by a few confident lines. No color — entirely monochrome black ink on dark paper. Dappled light implied by areas of lighter wash, not bright highlights. The mood is quiet and ancient, not threatening. Visible brushwork, paper texture, some areas left as raw graphite underdrawing showing through. Partially unfinished. Aspect ratio 16:9.`,
    variableSlots: ["location_name"],
    aspectRatio: "16:9",
    accentColor: "none",
    accentHex: null,
  },

  location_corrupted: {
    id: "location_corrupted",
    category: "location",
    name: "Corrupted / Hollow Location",
    promptText: `Ink wash illustration of {{location_name}}, a ruined stone temple overtaken by an unnatural force. The architecture is rendered in detailed ink work — crumbling columns, a fractured altar, fallen masonry — but the ink lines begin to distort and wobble in areas of corruption. Washes bleed where they shouldn't. A prominent teal watercolor stain spreads from the center of the composition outward, as if the color itself is a corruption — bleeding beyond the ink lines, pooling in cracks. The edges of the image dissolve into darkness and scattered marks. The teal is the only color. The rest is monochrome ink on near-black paper. The illustration itself looks like it's being consumed by the same force it depicts. Deeply atmospheric, unsettling. Fine art quality. Aspect ratio 16:9.`,
    variableSlots: ["location_name"],
    aspectRatio: "16:9",
    accentColor: "hollow_teal",
    accentHex: ACCENT_HEX.hollow_teal,
  },

  location_interior: {
    id: "location_interior",
    category: "location",
    name: "Interior — Tavern / Safe Space",
    promptText: `Ink wash interior of {{location_name}}, a medieval tavern, seen from a seat by the hearth. A stone fireplace dominates the center-right, rendered in warm ink detail. Wooden beams overhead, rough plaster walls. A few figures at tables are suggested loosely — shapes and postures rather than faces. The far wall dissolves into shadow and bare paper. Selective ember-orange watercolor wash radiates from the fireplace — warm, contained, the only color. Everything beyond the fire's glow is cool monochrome ink. The mood is safe, intimate, a pause between dangers. Ink bleed at edges, paper texture, visible brushwork. Partially unfinished. Aspect ratio 16:9.`,
    variableSlots: ["location_name"],
    aspectRatio: "16:9",
    accentColor: "ember",
    accentHex: ACCENT_HEX.ember,
  },

  item_weapon: {
    id: "item_weapon",
    category: "item",
    name: "Weapon",
    promptText: `Technical ink drawing of a single {{weapon_type}} on a plain dark background, centered with generous negative space around it. Rendered in fine nib ink — clean, precise linework showing the fuller, crossguard detail, leather-wrapped grip, and pommel. The blade catches a faint ember-orange highlight along one edge — a thin line of watercolor suggesting forge heat. Otherwise entirely monochrome. The style resembles a naturalist's specimen plate — the object studied and documented with care. No background detail, no hand holding it. Aged paper texture visible in the negative space. Fine art quality, meticulous. Aspect ratio 1:1.`,
    variableSlots: ["weapon_type"],
    aspectRatio: "1:1",
    accentColor: "ember",
    accentHex: ACCENT_HEX.ember,
  },

  item_corrupted_artifact: {
    id: "item_corrupted_artifact",
    category: "item",
    name: "Corrupted Artifact",
    promptText: `Technical ink drawing of {{item_description}} on a dark background, centered. Fine ink linework renders the details — {{item_features}}. The linework near the object begins to wobble and double, as if the artist's hand was unsteady. A teal watercolor stain bleeds outward from the center, spreading beyond the ink lines into the surrounding paper. The stain looks accidental but deliberate. The rest of the drawing is monochrome and precise. The contrast between the controlled linework and the spreading teal creates unease. Specimen plate style. Aspect ratio 1:1.`,
    variableSlots: ["item_description", "item_features"],
    aspectRatio: "1:1",
    accentColor: "hollow_teal",
    accentHex: ACCENT_HEX.hollow_teal,
  },

  item_quest: {
    id: "item_quest",
    category: "item",
    name: "Quest Item",
    promptText: `Technical ink drawing of {{item_description}} on a dark background. Fine nib ink renders {{item_features}}. Entirely monochrome — no color accents. Precise, detailed linework for the main object, with faint graphite sketch marks around the edges suggesting the artist's planning. Clean negative space. Naturalist specimen style. Aged paper texture. Aspect ratio 1:1.`,
    variableSlots: ["item_description", "item_features"],
    aspectRatio: "1:1",
    accentColor: "none",
    accentHex: null,
  },

  story_combat: {
    id: "story_combat",
    category: "story_moment",
    name: "Key Narrative Beat — Combat",
    promptText: `Dramatic ink wash illustration of a cloaked figure mid-swing with a longsword against a monstrous shadow. The figure is rendered in bold, energetic ink strokes — weight, motion, intensity captured in the brushwork. The monster is less defined — a mass of dark wash and jagged marks suggesting size and threat without clear anatomy. Ember-orange watercolor wash flares from the point of impact — sparks, heat, violence. The color bleeds into the surrounding ink. The background is pure darkness. The composition is tight and diagonal, like a graphic novel panel. Edges dissolve, but the central action is rendered with full intensity. Fine art quality, raw energy. Aspect ratio 2:3.`,
    variableSlots: [],
    aspectRatio: "2:3",
    accentColor: "ember",
    accentHex: ACCENT_HEX.ember,
  },

  story_god_contact: {
    id: "story_god_contact",
    category: "story_moment",
    name: "Key Narrative Beat — God Contact",
    promptText: `Ink wash illustration of a solitary figure kneeling in a vast empty space, looking upward. The figure is small in the composition — rendered in careful ink detail but dwarfed by negative space above. From above, a single shaft of pale golden light descends — the only color, applied as a delicate gold watercolor wash that barely touches the figure's upturned face. The gold is restrained, almost fragile. The surrounding space is deep black ink wash. The mood is awe, solitude, the weight of something sacred. Mostly negative space. Partially unfinished — the figure's lower half dissolves into scattered marks. Fine art quality, contemplative. Aspect ratio 2:3.`,
    variableSlots: [],
    aspectRatio: "2:3",
    accentColor: "divine_gold",
    accentHex: ACCENT_HEX.divine_gold,
  },

  story_hollow_encounter: {
    id: "story_hollow_encounter",
    category: "story_moment",
    name: "Key Narrative Beat — Hollow Encounter",
    promptText: `Ink wash illustration of a figure standing at the threshold of a doorway into wrongness. The figure is seen from behind — rendered in solid ink work, grounded, human. Beyond the doorway, the illustration itself breaks down. Ink lines wobble, double, and fragment. Washes bleed in unnatural directions. A deep teal watercolor stain dominates the space beyond the door — not illuminating anything, just present, spreading. The center of the space beyond the door is void — pure empty paper where something should be but isn't. The contrast between the solid figure and the corrupted space beyond is the entire composition. The art style itself is being consumed. Fine art quality, deeply unsettling. Aspect ratio 2:3.`,
    variableSlots: [],
    aspectRatio: "2:3",
    accentColor: "hollow_teal",
    accentHex: ACCENT_HEX.hollow_teal,
  },

  ui_app_store_bg: {
    id: "ui_app_store_bg",
    category: "ui",
    name: "App Store Screenshot Background",
    promptText: `Abstract ink wash composition on near-black background. Sweeping horizontal brush strokes in varying ink densities create atmospheric layers — like fog banks or geological strata. Entirely monochrome. No recognizable subject — pure atmosphere and texture. Some areas of fine ink splatter. Paper grain visible throughout. The composition should feel vast and empty, like standing at the edge of an abyss. Suitable as a background behind overlaid UI text. Fine art quality. Aspect ratio 9:16.`,
    variableSlots: [],
    aspectRatio: "9:16",
    accentColor: "none",
    accentHex: null,
  },

  ui_social_teaser: {
    id: "ui_social_teaser",
    category: "ui",
    name: "Social Media — Teaser Image",
    promptText: `Ink wash close-up of a single human eye on a dark background. The eye is rendered in exquisite detail — iris texture, reflected light, individual lashes. But the surrounding face dissolves immediately into loose ink marks and bare paper. Just the eye exists in full detail. A faint teal watercolor wash reflects in the iris — a hint of something the eye is seeing. The rest is monochrome. Intimate, unsettling, beautiful. The partially unfinished quality makes it feel like a memory of looking at something terrible. Fine art quality. Aspect ratio 1:1.`,
    variableSlots: [],
    aspectRatio: "1:1",
    accentColor: "hollow_teal",
    accentHex: ACCENT_HEX.hollow_teal,
  },

  ui_loading_abstract: {
    id: "ui_loading_abstract",
    category: "ui",
    name: "Loading Screen — Abstract",
    promptText: `Minimal ink composition on near-black background. A single vertical ink wash stroke, broad and gestural, rises from the bottom center. It begins as dense black ink and fades to nearly nothing at the top — dissolving into scattered marks and bare paper. The stroke has visible brush texture, ink bleed, and slight wobble. No other elements. No color. The composition is almost entirely negative space — a single mark in darkness. Meditative, atmospheric. Fine art quality. Aspect ratio 9:16.`,
    variableSlots: [],
    aspectRatio: "9:16",
    accentColor: "none",
    accentHex: null,
  },
};

/**
 * Resolve a prompt template by replacing {{variable}} placeholders.
 * Throws if templateId is unknown or a required variable is missing.
 */
export function resolvePrompt(
  templateId: string,
  vars: Record<string, string>,
): { prompt: string; template: ImagePromptTemplate } {
  const template = PROMPT_TEMPLATES[templateId];
  if (!template) {
    throw new Error(`Unknown template: ${templateId}`);
  }

  let prompt = template.promptText;

  for (const slot of template.variableSlots) {
    if (!(slot in vars)) {
      throw new Error(`Missing required variable "${slot}" for template "${templateId}"`);
    }
    prompt = prompt.replaceAll(`{{${slot}}}`, vars[slot]!);
  }

  return { prompt, template };
}
