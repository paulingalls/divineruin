#!/usr/bin/env bun
/**
 * Batch image generation CLI.
 *
 * Usage:
 *   bun run scripts/generate_art.ts --template <id> --vars '{"key":"value"}'
 *   bun run scripts/generate_art.ts --batch mvp
 */

import { generateImage } from "../apps/server/src/image-gen.ts";
import { PROMPT_TEMPLATES } from "../apps/server/src/image-prompt-templates.ts";
import { assetExists } from "../apps/server/src/image-gen.ts";

interface BatchEntry {
  templateId: string;
  vars: Record<string, string>;
  label: string;
}

const MVP_BATCH: BatchEntry[] = [
  // Companion portraits
  { templateId: "companion_portrait_primary", vars: {}, label: "Kael primary" },
  { templateId: "companion_portrait_alert", vars: {}, label: "Kael alert" },

  // Location illustrations
  {
    templateId: "location_town",
    vars: { location_name: "Market Square of Greyvale" },
    label: "Market Square",
  },
  {
    templateId: "location_interior",
    vars: { location_name: "The Hearthstone Tavern" },
    label: "Tavern",
  },
  {
    templateId: "location_wilderness",
    vars: { location_name: "the Forest Road outside Greyvale" },
    label: "Forest Road",
  },
  {
    templateId: "location_town",
    vars: { location_name: "Millhaven, a quiet hamlet on the river" },
    label: "Millhaven",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "the Ruins of the Old Seminary" },
    label: "Ruins Entrance",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "the inner sanctum of the corrupted ruins" },
    label: "Ruins Interior",
  },
  {
    templateId: "location_corrupted",
    vars: { location_name: "a breach in reality where the Hollow seeps through" },
    label: "Hollow Breach",
  },

  // NPC portraits
  {
    templateId: "npc_portrait",
    vars: {
      description: "a weathered male blacksmith in his fifties",
      features: "a broad scarred face, thick arms, and a leather apron",
    },
    label: "Torin",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "a young female herbalist with keen eyes",
      features: "sharp observant eyes, wild curly hair, and herb-stained fingers",
    },
    label: "Yanna",
  },
  {
    templateId: "npc_portrait",
    vars: {
      description: "an elderly male scholar with a haunted expression",
      features: "gaunt cheeks, round spectacles, and ink-stained hands clutching a journal",
    },
    label: "Emris",
  },

  // Item illustrations
  {
    templateId: "item_quest",
    vars: {
      item_description: "a sealed stone tablet covered in ancient runes",
      item_features: "the chisel marks, weathered edges, and faintly glowing inscriptions",
    },
    label: "Sealed Research Tablet",
  },
  {
    templateId: "item_corrupted_artifact",
    vars: {
      item_description: "a fragment of bone with an unnatural crystalline growth",
      item_features: "the porous bone texture and the faceted crystal emerging from within",
    },
    label: "Hollow-Bone Fragment",
  },

  // Loading screen
  { templateId: "ui_loading_abstract", vars: {}, label: "Loading screen" },
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
    vars = JSON.parse(varsJson);
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
      const result = await generateImage(entry.templateId, entry.vars);
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
