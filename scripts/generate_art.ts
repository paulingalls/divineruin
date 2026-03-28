#!/usr/bin/env bun
/**
 * Batch image generation CLI.
 *
 * Usage:
 *   bun run scripts/generate_art.ts --template <id> --vars '{"key":"value"}'
 *   bun run scripts/generate_art.ts --batch mvp
 */

import { generateImage, computeAssetId, getAssetPath } from "../apps/server/src/image-gen.ts";
import { PROMPT_TEMPLATES } from "../apps/server/src/image-prompt-templates.ts";

interface BatchEntry {
  templateId: string;
  vars: Record<string, string>;
  label: string;
  /** When set, use this slug as the asset ID instead of computing a hash. */
  assetId?: string;
  /** When set, the generated image is also copied to the mobile assets dir with this filename. */
  locationId?: string;
  /** When set, the generated image is also copied to the mobile marketing assets dir with this filename. */
  marketingId?: string;
}

const MVP_BATCH: BatchEntry[] = [
  // Companion portraits
  { templateId: "companion_portrait_primary", vars: {}, label: "Kael primary", assetId: "companion_kael_primary" },
  { templateId: "companion_portrait_alert", vars: {}, label: "Kael alert", assetId: "companion_kael_alert" },

  // Location illustrations — Accord of Tides
  {
    templateId: "location_town",
    vars: { location_name: "Market Square of the Accord of Tides" },
    label: "Market Square",
    assetId: "loc_accord_market_square",
    locationId: "accord_market_square",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "The Hearthstone Tavern" },
    label: "Tavern",
    assetId: "loc_accord_hearthstone_tavern",
    locationId: "accord_hearthstone_tavern",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "the Guild Hall of the Accord of Tides" },
    label: "Guild Hall",
    assetId: "loc_accord_guild_hall",
    locationId: "accord_guild_hall",
  },
  {
    templateId: "location_town",
    vars: { location_name: "Temple Row, an avenue lined with temples to four gods" },
    label: "Temple Row",
    assetId: "loc_accord_temple_row",
    locationId: "accord_temple_row",
  },
  {
    templateId: "location_town",
    vars: { location_name: "the Dockside Quarter of the Accord of Tides" },
    label: "Dockside",
    assetId: "loc_accord_dockside",
    locationId: "accord_dockside",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "Grimjaw's Forge, a roaring stone hearth with walls of weapons" },
    label: "Forge",
    assetId: "loc_accord_forge",
    locationId: "accord_forge",
  },

  // Location illustrations — Greyvale
  {
    templateId: "location_wilderness",
    vars: { location_name: "the South Road through barley fields outside the city" },
    label: "South Road",
    assetId: "loc_greyvale_south_road",
    locationId: "greyvale_south_road",
  },
  {
    templateId: "location_town",
    vars: { location_name: "Millhaven, a quiet hamlet on the river" },
    label: "Millhaven",
    assetId: "loc_millhaven",
    locationId: "millhaven",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "the Millhaven Inn, dim and half-empty" },
    label: "Millhaven Inn",
    assetId: "loc_millhaven_inn",
    locationId: "millhaven_inn",
  },
  {
    templateId: "location_wilderness",
    vars: { location_name: "the northern Greyvale wilderness, an unnaturally silent forest" },
    label: "Northern Wilds",
    assetId: "loc_greyvale_wilderness_north",
    locationId: "greyvale_wilderness_north",
  },
  {
    templateId: "location_wilderness",
    vars: { location_name: "the surface ruins of Greyvale, broken stones on a windswept hilltop" },
    label: "Ruins Surface",
    assetId: "loc_greyvale_ruins_exterior",
    locationId: "greyvale_ruins_exterior",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "the Ruins of the Old Seminary entrance hall" },
    label: "Ruins Entrance",
    assetId: "loc_greyvale_ruins_entrance",
    locationId: "greyvale_ruins_entrance",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "the inner sanctum of the corrupted ruins" },
    label: "Ruins Interior",
    assetId: "loc_greyvale_ruins_inner",
    locationId: "greyvale_ruins_inner",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "a breach in reality where the Hollow seeps through" },
    label: "Hollow Breach",
    assetId: "loc_hollow_incursion_site",
    locationId: "hollow_incursion_site",
  },

  // Location illustrations — NPC quarters
  {
    templateId: "location_interior",
    vars: { location_name: "Torin's Quarters, papers and maps covering every surface" },
    label: "Torin's Quarters",
    assetId: "loc_torin_quarters",
    locationId: "torin_quarters",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "Yanna's Farmhouse, worn but warm with dried herbs by the hearth" },
    label: "Yanna's Farmhouse",
    assetId: "loc_yanna_farmhouse",
    locationId: "yanna_farmhouse",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "Emris's Study, a scholar's workspace overlooking the harbor" },
    label: "Emris's Study",
    assetId: "loc_emris_study",
    locationId: "emris_study",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "Grimjaw's Quarters, a spare room above the forge" },
    label: "Grimjaw's Quarters",
    assetId: "loc_grimjaw_quarters",
    locationId: "grimjaw_quarters",
  },

  // NPC portraits (Tier 1)
  {
    templateId: "npc_portrait",
    vars: {
      description: "a broad-shouldered older man, guild leader",
      features: "weathered face, thick beard, shrewd eyes",
    },
    label: "Guildmaster Torin",
    assetId: "npc_torin",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "an elderly woman, village elder",
      features: "deep-set wise eyes, silver hair, lined face",
    },
    label: "Elder Yanna",
    assetId: "npc_yanna",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a young scholarly figure",
      features: "sharp focused eyes, ink-stained fingers, slight frame",
    },
    label: "Scholar Emris",
    assetId: "npc_emris",
  },

  // NPC portraits — Secondary characters
  {
    templateId: "npc_portrait",
    vars: {
      description: "a dust-caked young man, exhausted messenger",
      features: "bloodshot eyes, one arm in a sling, desperate expression",
    },
    label: "Wounded Rider",
    assetId: "npc_wounded_rider",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a sturdy woman in a flour-dusted apron, innkeeper",
      features: "sharp eyes with dark circles, hair pinned back, strong arms",
    },
    label: "Innkeeper Maren",
    assetId: "npc_maren",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a man in an immaculate dark coat with silver clasp, investigator",
      features: "calculating eyes that miss nothing, manicured hands, temple insignia",
    },
    label: "Investigator Valdris",
    assetId: "npc_valdris",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a barrel-chested dwarf blacksmith in a soot-streaked apron",
      features: "burn-scarred hands, beard braided tight, fierce focused eyes",
    },
    label: "Grimjaw",
    assetId: "npc_grimjaw",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a broad-hipped woman with dark hair streaked grey, tavern keeper",
      features: "warm observant eyes, hands that never stop moving, knowing smile",
    },
    label: "Tavern Keeper Bryn",
    assetId: "npc_bryn",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a tall Elari woman with silver-white hair in a single braid, temple warden",
      features: "serene distant gaze, robes that shift with light, eyes focused beyond you",
    },
    label: "Warden Selene",
    assetId: "npc_selene",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a gaunt hollow-eyed man sitting with unnatural stillness",
      features: "vacant stare, fingers twitching in patterns, something essential missing",
    },
    label: "Aldric",
    assetId: "npc_aldric",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a lean sharp-featured woman who moves like smoke, operative",
      features: "cataloguing eyes, thin scar along jawline, dark clothes blending with shadow",
    },
    label: "Nyx",
    assetId: "npc_nyx",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a neat young scholar in immaculate robes, archivist",
      features: "spectacles, nervous eager expression, leather satchel, fidgeting hands",
    },
    label: "Archivist Theron",
    assetId: "npc_theron",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a sturdy woman with calloused hands, guild master",
      features: "weathered honest face, guild chain with Aelora's mark, practical clothing",
    },
    label: "Guild Master Dara",
    assetId: "npc_dara",
  },

  // Item illustrations
  {
    templateId: "item_quest",
    vars: {
      item_description: "a sealed stone tablet covered in ancient runes",
      item_features: "the chisel marks, weathered edges, and faintly glowing inscriptions",
    },
    label: "Sealed Research Tablet",
    assetId: "item_sealed_research_tablet",
  },
  {
    templateId: "item_corrupted_artifact",
    vars: {
      item_description: "a fragment of bone with an unnatural crystalline growth",
      item_features: "the porous bone texture and the faceted crystal emerging from within",
    },
    label: "Hollow-Bone Fragment",
    assetId: "item_hollow_bone_fragment",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a torn vellum page with dense handwritten notation",
      item_features: "the age-darkened edges, precise lettering, and idiosyncratic notation system",
    },
    label: "Torn Journal Page",
    assetId: "item_torn_journal_page",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a small clay vial sealed with wax",
      item_features: "the rough clay texture, wax seal, and faint warmth from the liquid within",
    },
    label: "Healing Potion",
    assetId: "item_healing_potion",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a carved bone pendant on a leather cord",
      item_features: "the intricate carved patterns, smooth worn surface, and leather cord wrapping",
    },
    label: "Hollow Ward Charm",
    assetId: "item_hollow_ward_charm",
  },
  {
    templateId: "item_corrupted_artifact",
    vars: {
      item_description: "a smooth palm-sized stone with an iridescent surface",
      item_features: "the oil-like iridescence on the surface and shapes that seem to move beneath",
    },
    label: "Humming Stone",
    assetId: "item_humming_stone",
  },
  {
    templateId: "item_weapon",
    vars: { weapon_type: "shortsword" },
    label: "Shortsword",
    assetId: "item_shortsword",
  },
  {
    templateId: "item_weapon",
    vars: { weapon_type: "longsword with a small guild mark near the crossguard" },
    label: "Guild Longsword",
    assetId: "item_guild_longsword",
  },
  {
    templateId: "item_weapon",
    vars: { weapon_type: "balanced throwing dagger" },
    label: "Balanced Dagger",
    assetId: "item_balanced_dagger",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a suit of cured leather armor",
      item_features: "the stiffened leather panels, stitching, and oil-darkened surface",
    },
    label: "Leather Armor",
    assetId: "item_leather_armor",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a shirt of interlocking metal chain rings",
      item_features: "the tight even links, metal sheen, and compact folded form",
    },
    label: "Chain Shirt",
    assetId: "item_chain_shirt",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a round shield with an iron boss and wooden body",
      item_features: "the iron boss, dented rim, and grain of the wooden body",
    },
    label: "Iron Shield",
    assetId: "item_iron_shield",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a small crystal vial of blessed water",
      item_features: "the crystal facets, stoppered cork, and faint inner luminescence",
    },
    label: "Holy Water",
    assetId: "item_holy_water",
  },

  // New weapon types
  {
    templateId: "item_weapon",
    vars: { weapon_type: "short recurve hunting bow with a worn leather grip" },
    label: "Hunting Bow",
    assetId: "item_hunting_bow",
  },
  {
    templateId: "item_weapon",
    vars: { weapon_type: "iron-shod oak quarterstaff" },
    label: "Oak Quarterstaff",
    assetId: "item_oak_quarterstaff",
  },
  {
    templateId: "item_weapon",
    vars: { weapon_type: "flanged steel war mace with leather-wrapped handle" },
    label: "War Mace",
    assetId: "item_war_mace",
  },
  // Earned / discovered gear
  {
    templateId: "item_corrupted_artifact",
    vars: {
      item_description: "a short blade with a faint teal sheen along the edge",
      item_features: "the dark steel-and-bone alloy, the shifting teal edge, and runes etched into the fuller",
    },
    label: "Hollow-Edge Blade",
    assetId: "item_hollow_edge_blade",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a faceted crystal in a tarnished silver cage on a fine chain",
      item_features: "the multifaceted crystal surface, intricate silver cage work, and faint inner luminescence",
    },
    label: "Aelindran Focus Crystal",
    assetId: "item_aelindran_focus_crystal",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a plain iron ring with tiny engraved script on the inside",
      item_features: "the dark iron surface, microscopic interior engraving, and faint cold aura",
    },
    label: "Veil-Touched Ring",
    assetId: "item_veil_touched_ring",
  },
  // Armor additions
  {
    templateId: "item_quest",
    vars: {
      item_description: "a coat of overlapping steel scales riveted to leather backing",
      item_features: "the layered steel scales, leather straps, and rivet heads catching light",
    },
    label: "Scale Mail",
    assetId: "item_scale_mail",
  },
  {
    templateId: "item_quest",
    vars: {
      item_description: "a heavy dark wool cloak with a deep hood",
      item_features: "the dense weave, deep hood shadow, and folds that seem to absorb light",
    },
    label: "Traveler's Cloak",
    assetId: "item_travelers_cloak",
  },

  // Story moment illustrations
  { templateId: "story_combat", vars: {}, label: "Story: Combat Victory", assetId: "story_combat_victory" },
  { templateId: "story_god_contact", vars: {}, label: "Story: God Contact", assetId: "story_god_contact" },
  { templateId: "story_hollow_encounter", vars: {}, label: "Story: Hollow Encounter", assetId: "story_hollow_encounter" },

  // Loading screen
  { templateId: "ui_loading_abstract", vars: {}, label: "Loading screen", assetId: "ui_loading", locationId: "loading_abstract" },

  // --- Race portraits (6) ---
  { templateId: "race_portrait", vars: { race_name: "Draethar", physical_features: "Large and powerful, with inner fire. Skin radiates heat in moments of exertion." }, label: "Race: Draethar", assetId: "race_draethar" },
  { templateId: "race_portrait", vars: { race_name: "Elari", physical_features: "Tall and long-lived, with an innate sense of the Veil between worlds." }, label: "Race: Elari", assetId: "race_elari" },
  { templateId: "race_portrait", vars: { race_name: "Korath", physical_features: "Broad and stone-touched. Dense bones, earth-sense, and the patience of mountains." }, label: "Race: Korath", assetId: "race_korath" },
  { templateId: "race_portrait", vars: { race_name: "Vaelti", physical_features: "Slight and quick, with senses sharper than any other race. Impossible to surprise." }, label: "Race: Vaelti", assetId: "race_vaelti" },
  { templateId: "race_portrait", vars: { race_name: "Thessyn", physical_features: "Fluid and adaptable. Your body attunes to your environment over time." }, label: "Race: Thessyn", assetId: "race_thessyn" },
  { templateId: "race_portrait", vars: { race_name: "Human", physical_features: "Adaptable and determined. No extremes, but thrives anywhere and learns anything." }, label: "Race: Human", assetId: "race_human" },

  // --- Class illustrations (17) ---
  { templateId: "class_illustration", vars: { class_name: "Warrior", class_fantasy: "Front-line combatant. Decisive, aggressive, first to strike." }, label: "Class: Warrior", assetId: "class_warrior" },
  { templateId: "class_illustration", vars: { class_name: "Guardian", class_fantasy: "Protector of allies. Absorbs punishment, controls the battlefield." }, label: "Class: Guardian", assetId: "class_guardian" },
  { templateId: "class_illustration", vars: { class_name: "Skirmisher", class_fantasy: "Mobile fighter. Quick strikes, flanking, exploiting every opening." }, label: "Class: Skirmisher", assetId: "class_skirmisher" },
  { templateId: "class_illustration", vars: { class_name: "Mage", class_fantasy: "Classic spellcaster. Commands arcane energy through spoken incantations." }, label: "Class: Mage", assetId: "class_mage" },
  { templateId: "class_illustration", vars: { class_name: "Artificer", class_fantasy: "Magical inventor. Crafts enchanted items and deploys constructs." }, label: "Class: Artificer", assetId: "class_artificer" },
  { templateId: "class_illustration", vars: { class_name: "Seeker", class_fantasy: "Arcane investigator. Uses magic to perceive and uncover hidden truths." }, label: "Class: Seeker", assetId: "class_seeker" },
  { templateId: "class_illustration", vars: { class_name: "Druid", class_fantasy: "Channels nature's power. Shapes terrain, commands weather, speaks to the wild." }, label: "Class: Druid", assetId: "class_druid" },
  { templateId: "class_illustration", vars: { class_name: "Beastcaller", class_fantasy: "Bonds with creatures. Commands animal companions and draws on bestial instinct." }, label: "Class: Beastcaller", assetId: "class_beastcaller" },
  { templateId: "class_illustration", vars: { class_name: "Warden", class_fantasy: "Primal guardian bound to the land. Strongest in their home territory." }, label: "Class: Warden", assetId: "class_warden" },
  { templateId: "class_illustration", vars: { class_name: "Cleric", class_fantasy: "Divine channeler. Your patron god shapes your abilities entirely." }, label: "Class: Cleric", assetId: "class_cleric" },
  { templateId: "class_illustration", vars: { class_name: "Paladin", class_fantasy: "Sworn champion. Combines martial skill with a divine oath." }, label: "Class: Paladin", assetId: "class_paladin" },
  { templateId: "class_illustration", vars: { class_name: "Oracle", class_fantasy: "Fate-touched prophet. Receives visions and manipulates probability." }, label: "Class: Oracle", assetId: "class_oracle" },
  { templateId: "class_illustration", vars: { class_name: "Rogue", class_fantasy: "Skill specialist. Stealth, precision, and striking from the shadows." }, label: "Class: Rogue", assetId: "class_rogue" },
  { templateId: "class_illustration", vars: { class_name: "Spy", class_fantasy: "Social infiltrator. Deceives, disguises, and extracts secrets through talk." }, label: "Class: Spy", assetId: "class_spy" },
  { templateId: "class_illustration", vars: { class_name: "Whisper", class_fantasy: "Shadow-magic hybrid. Subtle spells of influence and misdirection." }, label: "Class: Whisper", assetId: "class_whisper" },
  { templateId: "class_illustration", vars: { class_name: "Bard", class_fantasy: "Performer and storyteller. Inspires allies, demoralizes foes with voice." }, label: "Class: Bard", assetId: "class_bard" },
  { templateId: "class_illustration", vars: { class_name: "Diplomat", class_fantasy: "Master negotiator. Solves encounters through persuasion and social leverage." }, label: "Class: Diplomat", assetId: "class_diplomat" },

  // --- Marketing assets ---
  { templateId: "ui_app_store_bg", vars: { variant: "1" }, label: "App Store BG 1", assetId: "marketing_app_store_bg_1", marketingId: "app_store_bg_1" },
  { templateId: "ui_app_store_bg", vars: { variant: "2" }, label: "App Store BG 2", assetId: "marketing_app_store_bg_2", marketingId: "app_store_bg_2" },
  { templateId: "ui_app_store_bg", vars: { variant: "3" }, label: "App Store BG 3", assetId: "marketing_app_store_bg_3", marketingId: "app_store_bg_3" },
  { templateId: "ui_app_store_bg", vars: { variant: "4" }, label: "App Store BG 4", assetId: "marketing_app_store_bg_4", marketingId: "app_store_bg_4" },
  { templateId: "ui_app_store_bg", vars: { variant: "5" }, label: "App Store BG 5", assetId: "marketing_app_store_bg_5", marketingId: "app_store_bg_5" },
  { templateId: "ui_social_teaser", vars: {}, label: "Social Teaser", assetId: "marketing_social_teaser", marketingId: "social_teaser" },
  { templateId: "ui_app_icon", vars: {}, label: "App Icon", assetId: "marketing_app_icon", marketingId: "app_icon" },

  // --- Deity cards (11) ---
  { templateId: "patron_deity_card", vars: { deity_name: "Veythar", deity_domain: "Knowledge, discovery, memory, the arcane arts" }, label: "Deity: Veythar", assetId: "deity_veythar" },
  { templateId: "patron_deity_card", vars: { deity_name: "Mortaen", deity_domain: "Death, the afterlife, transition" }, label: "Deity: Mortaen", assetId: "deity_mortaen" },
  { templateId: "patron_deity_card", vars: { deity_name: "Thyra", deity_domain: "Nature, seasons, growth, the physical world" }, label: "Deity: Thyra", assetId: "deity_thyra" },
  { templateId: "patron_deity_card", vars: { deity_name: "Kaelen", deity_domain: "War, conflict, valor, martial discipline" }, label: "Deity: Kaelen", assetId: "deity_kaelen" },
  { templateId: "patron_deity_card", vars: { deity_name: "Syrath", deity_domain: "Shadows, secrets, espionage, hidden knowledge" }, label: "Deity: Syrath", assetId: "deity_syrath" },
  { templateId: "patron_deity_card", vars: { deity_name: "Aelora", deity_domain: "Civilization, commerce, crafting, community" }, label: "Deity: Aelora", assetId: "deity_aelora" },
  { templateId: "patron_deity_card", vars: { deity_name: "Valdris", deity_domain: "Justice, law, order, truth, accountability" }, label: "Deity: Valdris", assetId: "deity_valdris" },
  { templateId: "patron_deity_card", vars: { deity_name: "Nythera", deity_domain: "Sea, travel, exploration, boundaries, the unknown" }, label: "Deity: Nythera", assetId: "deity_nythera" },
  { templateId: "patron_deity_card", vars: { deity_name: "Orenthel", deity_domain: "Light, healing, renewal, hope" }, label: "Deity: Orenthel", assetId: "deity_orenthel" },
  { templateId: "patron_deity_card", vars: { deity_name: "Zhael", deity_domain: "Fate, time, prophecy, luck, the pattern of things" }, label: "Deity: Zhael", assetId: "deity_zhael" },
  { templateId: "patron_deity_card", vars: { deity_name: "No Patron", deity_domain: "Independence" }, label: "Deity: None", assetId: "deity_none" },
];

async function runSingle(templateId: string, varsJson: string) {
  const template = PROMPT_TEMPLATES[templateId];
  if (!template) {
    console.error(`Unknown template: ${templateId}`);
    console.error(`Available: ${Object.keys(PROMPT_TEMPLATES).join(", ")}`);
    process.exit(1);
  }

  let vars: Record<string, string>;
  try {
    vars = JSON.parse(varsJson) as Record<string, string>;
  } catch {
    console.error("Invalid JSON for --vars");
    process.exit(1);
  }

  console.log(`Generating ${templateId}...`);
  const start = performance.now();
  const result = await generateImage(templateId, vars);
  const elapsed = ((performance.now() - start) / 1000).toFixed(1);
  console.log(`Done: ${result.assetId} (${elapsed}s)`);
  console.log(`File: ${result.path}`);
}

async function runBatch(batchName: string) {
  if (batchName !== "mvp") {
    console.error(`Unknown batch: ${batchName}. Available: mvp`);
    process.exit(1);
  }

  const total = MVP_BATCH.length;
  let generated = 0;
  let skipped = 0;
  const batchStart = performance.now();

  console.log(`\nGenerating ${total} MVP assets...\n`);

  for (let i = 0; i < total; i++) {
    const entry = MVP_BATCH[i]!;
    const prefix = `[${i + 1}/${total}]`;

    // Check for dedup before calling (to show skip message)
    process.stdout.write(`${prefix} Generating ${entry.templateId} (${entry.label})... `);

    const start = performance.now();
    try {
      const result = await generateImage(entry.templateId, entry.vars, entry.assetId ? { assetId: entry.assetId } : undefined);
      const elapsed = ((performance.now() - start) / 1000).toFixed(1);

      // If it completed in under 500ms, it was likely a cache hit
      if (performance.now() - start < 500) {
        console.log(`skipped (cached: ${result.assetId})`);
        skipped++;
      } else {
        console.log(`done (${result.assetId}) ${elapsed}s`);
        generated++;
      }
    } catch (err) {
      const elapsed = ((performance.now() - start) / 1000).toFixed(1);
      console.log(`FAILED ${elapsed}s`);
      console.error(`  Error: ${err instanceof Error ? err.message : String(err)}`);
    }

    // Rate limit delay between API calls (skip for cached results)
    if (i < total - 1 && performance.now() - start > 500) {
      await Bun.sleep(2000);
    }
  }

  const totalElapsed = ((performance.now() - batchStart) / 1000).toFixed(1);
  console.log(`\n--- Summary ---`);
  console.log(`Generated: ${generated}`);
  console.log(`Skipped (cached): ${skipped}`);
  console.log(`Failed: ${total - generated - skipped}`);
  console.log(`Total time: ${totalElapsed}s`);
  console.log(`Est. cost: ~$${(generated * 0.04).toFixed(2)} (at ~$0.04/image)`);

  // Copy assets to mobile bundle directories
  const mobileBase = `${import.meta.dir}/../apps/mobile/assets/images`;
  await copyBatchAssets("locationId", `${mobileBase}/locations`, "location");
  await copyBatchAssets("marketingId", `${mobileBase}/marketing`, "marketing");
}

async function copyBatchAssets(
  filterKey: "locationId" | "marketingId",
  destDir: string,
  label: string,
) {
  await Bun.$`mkdir -p ${destDir}`;

  const entries = MVP_BATCH.filter((e) => e[filterKey]);
  let copied = 0;

  console.log(`\nCopying ${entries.length} ${label} assets to mobile bundle...`);

  for (const entry of entries) {
    const assetId = entry.assetId ?? computeAssetId(entry.templateId, entry.vars);
    const srcPath = getAssetPath(assetId);
    const destName = entry[filterKey]!;
    const dest = `${destDir}/${destName}.png`;
    const src = Bun.file(srcPath);
    if (await src.exists()) {
      await Bun.write(dest, src);
      copied++;
    } else {
      console.warn(`  Warning: source not found for ${destName} (${srcPath})`);
    }
  }

  console.log(`Copied ${copied}/${entries.length} ${label} assets.`);
}

// Parse CLI args
const args = process.argv.slice(2);
const flagIndex = (flag: string) => args.indexOf(flag);

if (flagIndex("--batch") !== -1) {
  const batchName = args[flagIndex("--batch") + 1];
  if (!batchName) {
    console.error("Usage: --batch <name>");
    process.exit(1);
  }
  await runBatch(batchName);
} else if (flagIndex("--template") !== -1) {
  const templateId = args[flagIndex("--template") + 1];
  const varsIdx = flagIndex("--vars");
  const varsJson = varsIdx !== -1 ? args[varsIdx + 1] ?? "{}" : "{}";
  if (!templateId) {
    console.error("Usage: --template <id> [--vars '{...}']");
    process.exit(1);
  }
  await runSingle(templateId, varsJson);
} else {
  console.log("Image generation CLI for Divine Ruin");
  console.log("");
  console.log("Usage:");
  console.log("  bun run scripts/generate_art.ts --template <id> [--vars '{...}']");
  console.log("  bun run scripts/generate_art.ts --batch mvp");
  console.log("");
  console.log(`Templates: ${Object.keys(PROMPT_TEMPLATES).join(", ")}`);
}
